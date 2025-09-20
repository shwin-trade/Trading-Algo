import os
import sys
import json
import time
import threading
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
import requests
import pyotp
import base64
import subprocess
import logging
import hashlib
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
from ratelimit import limits, sleep_and_retry
import functools
from typing import Dict, List, Optional, Any, Tuple

# Import base broker classes
from .base import BrokerBase

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

from dotenv import load_dotenv
load_dotenv()


# Rate limiting configuration for Fyers API
# Per Second: 10, Per Minute: 200, Per Day: 100000
def fyers_rate_limit(func):
    """
    A decorator to enforce Fyers API rate limits on a function.

    This decorator applies multiple rate limits:
    - 10 calls per second
    - 200 calls per minute
    - 100,000 calls per day

    If a limit is exceeded, the decorator will pause execution and retry.

    Args:
        func (callable): The function to be rate-limited.

    Returns:
        callable: The wrapped function with rate limiting applied.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Rate limiting applied to {func.__name__}")
        return func(*args, **kwargs)
    
    # Apply the rate limiting decorators in order
    wrapper = sleep_and_retry(limits(calls=10, period=1))(wrapper)
    wrapper = sleep_and_retry(limits(calls=200, period=60))(wrapper)
    wrapper = sleep_and_retry(limits(calls=100000, period=86400))(wrapper)
    
    return wrapper

def getEncodedString(string: str) -> str:
    """
    Encodes a string to a Base64 ASCII string.

    Args:
        string (str): The input string to encode.

    Returns:
        str: The Base64 encoded string.
    """
    return base64.b64encode(str(string).encode("ascii")).decode("ascii")


class FyersBroker(BrokerBase):
    """
    A broker implementation for Fyers API v3.

    This class provides a comprehensive interface for interacting with the Fyers
    platform, including both REST API for historical data, quotes, and order
    management, and a WebSocket connection for live data streaming.

    It handles the complete TOTP-based authentication flow, rate limiting,
    and session management.

    Attributes:
        fyers_model (fyersModel.FyersModel): The Fyers API model instance for
            making REST API calls.
        symbols (list): A list of symbols for WebSocket subscription.
        data_type (str): The type of data to subscribe to via WebSocket.
        ws (FyersDataSocket): The Fyers WebSocket instance.
    """

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        data_type: str = "SymbolUpdate",
        log_path: str = "",
        litemode: bool = False,
        write_to_file: bool = False,
        reconnect: bool = True,
        data_handler: Optional[Any] = None,
    ):
        """
        Initializes the FyersBroker instance.

        This sets up the Fyers API model, performs authentication, and configures
        parameters for the WebSocket connection.

        Args:
            symbols (list, optional): A list of symbols to subscribe to for live
                data. Defaults to a sample list.
            data_type (str, optional): The type of WebSocket data to receive
                (e.g., "SymbolUpdate", "OrderUpdate"). Defaults to "SymbolUpdate".
            log_path (str, optional): The path to store logs. Defaults to "".
            litemode (bool, optional): Whether to use litemode for WebSocket.
                Defaults to False.
            write_to_file (bool, optional): Whether to write WebSocket data to
                a file. Defaults to False.
            reconnect (bool, optional): Whether the WebSocket should attempt to
                reconnect on disconnection. Defaults to True.
            data_handler (any, optional): An object with a `data_queue` to which
                live data will be pushed. Defaults to None.
        """
        logger.info("Initializing FyersBroker...")
        self.access_token, self.auth_response_data = self.authenticate()
        self.fyers_model = fyersModel.FyersModel(
            client_id=os.environ["BROKER_API_KEY"],
            token=self.access_token,
            is_async=False,
            log_path=os.getcwd(),
        )
        self._init_context()

        # WebSocket parameters
        self.symbols = symbols or ["NSE:SBIN-EQ", "NSE:ADANIENT-EQ"]
        self.data_type = data_type
        self.log_path = log_path
        self.litemode = litemode
        self.write_to_file = write_to_file
        self.reconnect = reconnect
        self.data_handler = data_handler
        self.ws = None

        self._benchmark = False
        self.ticker_second_counts = {}
        self.minute_seconds_count = 0
        self.cumulative_distinct_tickers = 0
        self.cumulative_ticker_counts = {}
        self.benchmark_lock = threading.Lock()
        if self._benchmark:
            threading.Thread(target=self._aggregate_second, daemon=True).start()
            threading.Thread(target=self._benchmark_minute, daemon=True).start()
    
    def authenticate(self) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Performs the TOTP-based authentication flow for Fyers API v3.

        This method automates the multi-step authentication process:
        1. Sends a login OTP request.
        2. Verifies the TOTP.
        3. Verifies the user's PIN.
        4. Obtains an authorization code.
        5. Exchanges the auth code for a final access token.

        It requires several environment variables to be set, including
        `BROKER_ID`, `BROKER_TOTP_KEY`, `BROKER_API_KEY`, etc.

        Returns:
            A tuple containing the access token (str) and the full
            authentication response data (dict) if successful. If it fails,
            returns (None, error_data_dict).
        """
        response_data = {
            'status': 'error',
            'message': 'Authentication failed',
            'data': None
        }
        try:
            fy_id = os.environ['BROKER_ID']
            totp_key = os.environ['BROKER_TOTP_KEY']
            pin = os.environ['BROKER_TOTP_PIN']
            client_id = os.environ['BROKER_API_KEY']
            secret_key = os.environ['BROKER_API_SECRET']
            redirect_uri = os.environ['BROKER_TOTP_REDIDRECT_URI']
            response_type = "code"
            grant_type = "authorization_code"

            URL_SEND_LOGIN_OTP = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
            res = requests.post(url=URL_SEND_LOGIN_OTP, json={
                "fy_id": getEncodedString(fy_id),
                "app_id": "2"
            }).json()

            if datetime.now().second % 30 > 27:
                time.sleep(5)

            URL_VERIFY_OTP = "https://api-t2.fyers.in/vagator/v2/verify_otp"
            res2 = requests.post(url=URL_VERIFY_OTP, json={
                "request_key": res["request_key"],
                "otp": pyotp.TOTP(totp_key).now()
            }).json()

            ses = requests.Session()
            URL_VERIFY_PIN = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
            payload2 = {
                "request_key": res2["request_key"],
                "identity_type": "pin",
                "identifier": getEncodedString(pin)
            }
            res3 = ses.post(url=URL_VERIFY_PIN, json=payload2).json()
            ses.headers.update({
                'authorization': f"Bearer {res3['data']['access_token']}"
            })

            URL_TOKEN = "https://api-t1.fyers.in/api/v3/token"
            payload3 = {
                "fyers_id": fy_id,
                "app_id": client_id[:-4],
                "redirect_uri": redirect_uri,
                "appType": "100",
                "code_challenge": "",
                "state": "None",
                "scope": "",
                "nonce": "",
                "response_type": "code",
                "create_cookie": True
            }
            res4 = ses.post(url=URL_TOKEN, json=payload3).json()
            parsed = urlparse(res4['Url'])
            auth_code = parse_qs(parsed.query)['auth_code'][0]

            URL_VALIDATE_AUTHCODE = 'https://api-t1.fyers.in/api/v3/validate-authcode'
            checksum_input = f"{client_id}:{secret_key}"
            app_id_hash = hashlib.sha256(checksum_input.encode('utf-8')).hexdigest()
            payload = {
                'grant_type': grant_type,
                'appIdHash': app_id_hash,
                'code': auth_code
            }
            response = ses.post(URL_VALIDATE_AUTHCODE, headers={'Content-Type': 'application/json'}, json=payload, timeout=30.0)
            response.raise_for_status()
            auth_data = response.json()

            if auth_data.get('s') == 'ok':
                access_token = auth_data.get('access_token')
                if not access_token:
                    response_data['message'] = "Authentication succeeded but no access token was returned"
                    return None, response_data
                response_data.update({
                    'status': 'success',
                    'message': 'Authentication successful',
                    'data': auth_data
                })
                return access_token, response_data
            else:
                response_data['message'] = f"API error: {auth_data.get('message', 'Authentication failed')}"
                return None, response_data
        except Exception as e:
            response_data['message'] = f"Authentication failed: {str(e)}"
            return None, response_data

    def _aggregate_second(self):
        """(Internal) Accumulates per-second data for benchmarking."""
        while True:
            time.sleep(1)
            with self.benchmark_lock:
                current_counts = self.ticker_second_counts
                self.ticker_second_counts = {}
            distinct_this_second = len(current_counts)
            with self.benchmark_lock:
                self.minute_seconds_count += 1
                self.cumulative_distinct_tickers += distinct_this_second
                for ticker, count in current_counts.items():
                    self.cumulative_ticker_counts[ticker] = self.cumulative_ticker_counts.get(ticker, 0) + count

    def _benchmark_minute(self):
        """(Internal) Computes and prints benchmark stats every minute."""
        while True:
            time.sleep(60)
            with self.benchmark_lock:
                if self.minute_seconds_count == 0:
                    continue
                avg_distinct = self.cumulative_distinct_tickers / self.minute_seconds_count
                report_lines = [
                    "Benchmark (over last minute):",
                    f"Average distinct tickers per second: {avg_distinct:.2f}"
                ]
                tickers_counts = sum(1 for count in self.cumulative_ticker_counts.values() if count > 0)
                total_counts = sum(self.cumulative_ticker_counts.values())
                avg_msgs = total_counts / self.minute_seconds_count
                report_lines.append(f"Summary Records per Second\t {avg_msgs:.2f} from {tickers_counts} tickers - {total_counts} records in {self.minute_seconds_count} seconds")
                print("\n" + "\n".join(report_lines))

                self.minute_seconds_count = 0
                self.cumulative_distinct_tickers = 0
                self.cumulative_ticker_counts = {}

    def _init_context(self):
        """(Internal) Initializes a context file for tracking API calls."""
        if os.path.exists("FyersModel.json"):
            with open("FyersModel.json", "r") as f:
                self.context = json.load(f)
            if self.context.get("DATE") != str(datetime.now().date()):
                self._create_context()
        else:
            self._create_context()

    def _create_context(self):
        """(Internal) Creates a new context file."""
        self.context = {"TOTAL_API_CALLS": 0, "DATE": str(datetime.now().date())}
        with open("FyersModel.json", "w") as f:
            json.dump(self.context, f)

    def update_context(self):
        """(Internal) Updates the API call count in the context file."""
        self.context["TOTAL_API_CALLS"] += 1
        with open("FyersModel.json", "w") as f:
            json.dump(self.context, f)

    def get_access_token(self) -> Optional[str]:
        """
        Retrieves the current access token.

        Returns:
            The access token string, or None if not authenticated.
        """
        return self.access_token

    @fyers_rate_limit
    def get_history(self, symbol: str, resolution: str, start_date: str, end_date: str, oi_flag: bool = False) -> Dict[str, Any]:
        """
        Retrieves historical market data for a symbol.

        This method handles API limitations by automatically breaking down long
        date ranges into smaller chunks acceptable by the Fyers API.

        Args:
            symbol (str): The trading symbol (e.g., "NSE:SBIN-EQ").
            resolution (str): The timeframe resolution (e.g., "1", "D", "5S").
            start_date (str): The start date in "YYYY-MM-DD" format.
            end_date (str): The end date in "YYYY-MM-DD" format.
            oi_flag (bool, optional): Whether to fetch Open Interest data.
                Defaults to False.

        Returns:
            A dictionary containing the historical data, typically with a
            'candles' key.
        """
        formatted_symbol = f"NSE:{symbol}-EQ" if not symbol.startswith("NSE") else symbol
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        if resolution in ["D", "1D"]:
            max_days = 366
        elif resolution.endswith("S"):
            max_days = 30
        else:
            max_days = 100

        all_candles = []
        current_start = start_dt
        while current_start <= end_dt:
            current_end = min(current_start + timedelta(days=max_days - 1), end_dt)
            chunk_start = current_start.strftime("%Y-%m-%d")
            chunk_end = current_end.strftime("%Y-%m-%d")

            logger.info(f"Fetching {formatted_symbol} data from {chunk_start} to {chunk_end} with resolution {resolution}")

            data_headers = {
                "symbol": formatted_symbol, "resolution": resolution,
                "date_format": "1", "range_from": chunk_start,
                "range_to": chunk_end, "cont_flag": "1"
            }
            if oi_flag:
                data_headers["oi_flag"] = "1"

            chunk_data = self.fyers_model.history(data_headers)
            self.update_context()

            if "candles" in chunk_data and chunk_data["candles"]:
                all_candles.extend(chunk_data["candles"])

            time.sleep(0.5)
            current_start = current_end + timedelta(days=1)

        if not all_candles:
            return {"s": "no_data", "candles": []}

        return {"s": "ok", "candles": all_candles}
    
    @fyers_rate_limit
    def get_option_chain(self, data: dict, strikecount: int = 5) -> Dict[str, Any]:
        """
        Retrieves the option chain for a given underlying symbol.

        Args:
            data (dict): A dictionary containing parameters like 'symbol'.
            strikecount (int, optional): The number of strikes to fetch around
                the ATM. Defaults to 5.

        Returns:
            A dictionary containing the option chain data.
        """
        data["strikecount"] = strikecount
        result = self.fyers_model.optionchain(data)
        self.update_context()
        return result

    @fyers_rate_limit
    def get_quotes(self, data: dict) -> Dict[str, Any]:
        """
        Retrieves real-time quotes for one or more symbols.

        Args:
            data (dict): A dictionary containing a 'symbols' key with a
                comma-separated string of symbols.

        Returns:
            A dictionary containing the quote data.
        """
        result = self.fyers_model.quotes(data)
        self.update_context()
        return result

    @fyers_rate_limit
    def get_margin(self, symbols: list, use_curl: bool = True) -> Dict[str, Any]:
        """
        Calculates the required margin for a list of symbols.

        Args:
            symbols (list): A list of trading symbols.
            use_curl (bool, optional): Whether to use a `curl` subprocess
                for the request. Defaults to True.

        Returns:
            A dictionary with symbols as keys and their margin leverage as values,
            or an error dictionary.
        """
        url = "https://api-t1.fyers.in/api/v3/multiorder/margin"
        headers = {"Authorization": f"{os.environ['BROKER_API_KEY']}:{self.access_token}"}
        data = {"symbols": ",".join(symbols)}
        fyers = fyersModel.FyersModel(client_id=os.environ["BROKER_API_KEY"], token=self.access_token, is_async=False, log_path="")
        MARGIN_DICT = {}

        response_q = fyers.quotes(data=data)
        for i, symbol in enumerate(symbols):
            order_template = [{"symbol": symbol, "qty": 1, "side": 1, "type": 2, "productType": "INTRADAY"}]
            payload = json.dumps({"data": order_template})

            try:
                if use_curl:
                    curl_command = ["curl", "-X", "POST", url, "-H", f"Authorization: {headers['Authorization']}", "-H", "Content-Type: application/json", "--data-raw", payload]
                    result = subprocess.run(curl_command, capture_output=True, text=True, check=True)
                    response_json = json.loads(result.stdout)
                else:
                    response = requests.post(url, headers=headers, data=payload)
                    response.raise_for_status()
                    response_json = response.json()

                margin_total = response_json.get("data", {}).get("margin_total")
                lp = response_q.get("d", [])[i].get("v", {}).get("lp")
                MARGIN_DICT[symbol] = round(lp / margin_total) if margin_total else 1
            except Exception as e:
                logger.error(f"Failed to get margin for {symbol}: {e}")
                MARGIN_DICT[symbol] = 1
            time.sleep(1)
        return MARGIN_DICT

    def connect_websocket(self) -> data_ws.FyersDataSocket:
        """
        Establishes and returns a WebSocket connection for live data.

        It configures the WebSocket client with the parameters provided during
        initialization and sets up the internal callbacks for handling messages,
        connection open/close events.

        Returns:
            The configured and connected FyersDataSocket instance.
        """
        self.ws = data_ws.FyersDataSocket(
            access_token=self.access_token,
            log_path=self.log_path,
            litemode=self.litemode,
            write_to_file=self.write_to_file,
            reconnect=self.reconnect,
            on_connect=self._on_ws_open,
            on_close=self._on_ws_close,
            on_message=self._on_ws_message,
        )
        self.ws.connect()
        return self.ws

    def _on_ws_message(self, message: Dict[str, Any]):
        """(Internal) Callback for handling incoming WebSocket messages."""
        print(message)
        if "symbol" in message:
            if self._benchmark:
                with self.benchmark_lock:
                    self.ticker_second_counts[message["symbol"]] = self.ticker_second_counts.get(message["symbol"], 0) + 1
            if self.data_handler and hasattr(self.data_handler, 'data_queue'):
                self.data_handler.data_queue.put(message)

    def _on_ws_close(self, message: Dict[str, Any]):
        """(Internal) Callback for WebSocket connection closure."""
        print("WebSocket connection closed:", message)

    def _on_ws_open(self):
        """(Internal) Callback for successful WebSocket connection."""
        print("WebSocket connection opened. Subscribing to symbols.")
        self.ws.subscribe(symbols=self.symbols, data_type=self.data_type)
        self.ws.keep_running()
