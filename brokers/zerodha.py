import logging
import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Dict, Any, Optional, List, Tuple
import requests
import hashlib, pyotp
from dotenv import load_dotenv
from brokers.base import BrokerBase
from kiteconnect import KiteConnect, KiteTicker
import pandas as pd
from threading import Thread

from logger import logger

load_dotenv()

class ZerodhaBroker(BrokerBase):
    """
    A broker implementation for Zerodha's Kite Connect API.

    This class provides an interface for interacting with the Zerodha trading
    platform. It handles both automated TOTP-based authentication and a manual
    `request_token` flow. It supports placing regular and GTT orders,
    fetching quotes and positions, and connecting to the WebSocket for live data.

    Attributes:
        kite (KiteConnect): The KiteConnect client instance for REST API calls.
        kite_ws (KiteTicker): The KiteTicker instance for WebSocket streaming.
        instruments_df (pd.DataFrame): A DataFrame containing all available
            trading instruments.
        symbols (list): A list of instrument tokens to subscribe to for WebSocket
            data.
    """
    def __init__(self, without_totp: bool):
        """
        Initializes the ZerodhaBroker instance.

        Args:
            without_totp (bool): If True, initiates a manual authentication
                flow requiring user input for the request token. If False,
                attempts an automated login using environment variables.
        """
        super().__init__()
        self.without_totp = without_totp
        self.kite, self.auth_response_data = self.authenticate()
        self.access_token = self.auth_response_data.get("access_token")
        self.kite_ws = KiteTicker(api_key=os.getenv('BROKER_API_KEY'), access_token=self.access_token)
        self.tick_counter = 0
        self.symbols = []
        
    def authenticate(self) -> Tuple[KiteConnect, Dict[str, Any]]:
        """
        Authenticates with the Kite Connect API.

        Supports two modes:
        1.  `without_totp=True`: Prints a login URL and prompts the user to
            manually enter the `request_token` from the redirect URL.
        2.  `without_totp=False`: Attempts a fully automated login using
            credentials and TOTP secret from environment variables.

        Raises:
            Exception: If authentication fails at any step.

        Returns:
            A tuple containing the initialized `KiteConnect` instance and the
            authentication response data dictionary.
        """
        api_key = os.getenv('BROKER_API_KEY')
        api_secret = os.getenv('BROKER_API_SECRET')

        if self.without_totp:
            kite = KiteConnect(api_key=api_key)
            print(f"Please Login to Zerodha and get the request token from the URL.\n {kite.login_url()} \nThen paste the request token here:")
            request_token = input("Request Token: ")
            resp = kite.generate_session(request_token, api_secret)
            return kite, resp
        
        broker_id = os.getenv('BROKER_ID')
        totp_secret = os.getenv('BROKER_TOTP_KEY')
        password = os.getenv('BROKER_PASSWORD')

        if not all([api_key, api_secret, broker_id, totp_secret, password]):
            raise Exception("Missing one or more required environment variables for automated login.")

        session = requests.Session()

        login_url = "https://kite.zerodha.com/api/login"
        login_payload = {"user_id": broker_id, "password": password}
        login_resp = session.post(login_url, data=login_payload)
        login_data = login_resp.json()
        if not login_data.get("data"):
            raise Exception(f"Login failed: {login_data}")
        request_id = login_data["data"]["request_id"]

        twofa_url = "https://kite.zerodha.com/api/twofa"
        twofa_payload = {
            "user_id": broker_id,
            "request_id": request_id,
            "twofa_value": pyotp.TOTP(totp_secret).now(),
        }
        twofa_resp = session.post(twofa_url, data=twofa_payload)
        if not twofa_resp.json().get("data"):
            raise Exception(f"2FA failed: {twofa_resp.json()}")

        kite = KiteConnect(api_key=api_key)
        connect_url = f"https://kite.trade/connect/login?api_key={api_key}"
        connect_resp = session.get(connect_url, allow_redirects=True)
        if "request_token=" not in connect_resp.url:
            raise Exception("Failed to get request_token from redirect URL.")
        request_token = connect_resp.url.split("request_token=")[1].split("&")[0]

        resp = kite.generate_session(request_token, api_secret)
        return kite, resp
    
    def get_orders(self) -> List[Dict[str, Any]]:
        """
        Retrieves the list of all orders for the day.

        Returns:
            A list of order dictionaries.
        """
        return self.kite.orders()
    
    def get_quote(self, symbol: str, exchange: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves a full quote for one or more instruments.

        Args:
            symbol (str): The trading symbol (e.g., "SBIN" or "NFO:NIFTY25JANFUT").
                Can also be a list of symbols.
            exchange (str, optional): The exchange ("NSE", "NFO", etc.). If not
                provided, it's assumed the exchange is part of the symbol string.

        Returns:
            A dictionary of quote data, with instrument identifiers as keys.
        """
        if exchange and ":" not in symbol:
            symbol = f"{exchange}:{symbol}"
        return self.kite.quote(symbol)
    
    def place_gtt_order(self, symbol: str, quantity: int, price: float, transaction_type: str, order_type: str, exchange: str, product: str, tag: str = "Unknown") -> int:
        """
        Places a Good Till Triggered (GTT) order.

        Args:
            symbol (str): The trading symbol.
            quantity (int): The order quantity.
            price (float): The trigger price.
            transaction_type (str): "BUY" or "SELL".
            order_type (str): "LIMIT" or "MARKET".
            exchange (str): The exchange (e.g., "NFO").
            product (str): The product type (e.g., "NRML").
            tag (str, optional): An optional tag for the order.

        Returns:
            The trigger ID of the placed GTT order.
        """
        order_obj = {
            "exchange": exchange, "tradingsymbol": symbol,
            "transaction_type": transaction_type, "quantity": quantity,
            "order_type": order_type, "product": product,
            "price": price, "tag": tag
        }
        last_price = self.get_quote(symbol, exchange)[f"{exchange}:{symbol}"]['last_price']
        gtt_resp = self.kite.place_gtt(
            trigger_type=self.kite.GTT_TYPE_SINGLE, tradingsymbol=symbol,
            exchange=exchange, trigger_values=[price], last_price=last_price,
            orders=[order_obj]
        )
        return gtt_resp['trigger_id']
    
    def place_order(self, symbol: str, quantity: int, price: Optional[float], transaction_type: str, order_type: str, variety: str, exchange: str, product: str, tag: str = "Unknown") -> int:
        """
        Places a regular buy or sell order.

        Args:
            symbol (str): The trading symbol.
            quantity (int): The order quantity.
            price (float, optional): The price for LIMIT orders. Must be None for
                MARKET orders.
            transaction_type (str): "BUY" or "SELL".
            order_type (str): "LIMIT" or "MARKET".
            variety (str): The order variety (e.g., "REGULAR").
            exchange (str): The exchange (e.g., "NFO").
            product (str): The product type (e.g., "NRML").
            tag (str, optional): An optional tag for the order.

        Returns:
            The order ID if placement is successful, otherwise -1.
        """
        # Map string arguments to KiteConnect constants
        order_type_map = {"LIMIT": self.kite.ORDER_TYPE_LIMIT, "MARKET": self.kite.ORDER_TYPE_MARKET}
        trans_type_map = {"BUY": self.kite.TRANSACTION_TYPE_BUY, "SELL": self.kite.TRANSACTION_TYPE_SELL}
        variety_map = {"REGULAR": self.kite.VARIETY_REGULAR}

        if order_type not in order_type_map or transaction_type not in trans_type_map or variety not in variety_map:
            raise ValueError("Invalid order parameter provided.")

        logger.info(f"Placing order: {symbol} Qty:{quantity} Type:{order_type} Trans:{transaction_type}")
        try:
            for _ in range(5): # Retry mechanism
                order_id = self.kite.place_order(
                    variety=variety_map[variety], exchange=exchange,
                    tradingsymbol=symbol, transaction_type=trans_type_map[transaction_type],
                    quantity=quantity, product=product,
                    order_type=order_type_map[order_type],
                    price=price if order_type == 'LIMIT' else None,
                    tag=tag
                )
                if order_id:
                    logger.info(f"Order placed successfully: {order_id}")
                    return order_id
            logger.error("Order placement failed after 5 attempts.")
            return -1
        except Exception as e:
            logger.error(f"Order placement failed: {e}", exc_info=True)
            return -1

    def get_positions(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Retrieves the current open positions.

        Returns:
            A dictionary with 'net' and 'day' keys, each containing a list of
            position dictionaries.
        """
        return self.kite.positions()

    def symbols_to_subscribe(self, symbols: List[int]):
        """
        Sets the list of instrument tokens to be subscribed to via WebSocket.

        Args:
            symbols (list[int]): A list of instrument tokens.
        """
        self.symbols = symbols

    ## WebSocket Callbacks
    def on_ticks(self, ws, ticks):
        """WebSocket callback for receiving live ticks."""
        logger.info("Ticks: {}".format(ticks))

    def on_connect(self, ws, response):
        """WebSocket callback for successful connection."""
        logger.info("Connected to WebSocket")
        ws.subscribe(self.symbols)
        ws.set_mode(ws.MODE_FULL, self.symbols)

    def on_order_update(self, ws, data):
        """WebSocket callback for receiving order updates."""
        logger.info("Order update: {}".format(data))

    def on_close(self, ws, code, reason):
        """WebSocket callback for connection closure."""
        logger.info("Connection closed: {code} - {reason}".format(code=code, reason=reason))

    def on_error(self, ws, code, reason):
        """WebSocket callback for connection errors."""
        logger.info("Connection error: {code} - {reason}".format(code=code, reason=reason))

    def on_reconnect(self, ws, attempts_count):
        """WebSocket callback during reconnection attempts."""
        logger.info("Reconnecting: {}".format(attempts_count))

    def on_noreconnect(self, ws):
        """WebSocket callback when reconnection fails after all attempts."""
        logger.info("Reconnect failed.")
    
    def download_instruments(self):
        """
        Downloads the latest list of all tradable instruments and stores them
        in a pandas DataFrame.
        """
        instruments = self.kite.instruments()
        self.instruments_df = pd.DataFrame(instruments)
    
    def get_instruments(self) -> pd.DataFrame:
        """
        Returns the DataFrame of all tradable instruments.

        Returns:
            A pandas DataFrame containing instrument data.
        """
        return self.instruments_df
    
    def connect_websocket(self):
        """
        Assigns the callbacks and starts the WebSocket connection in a new thread.
        """
        self.kite_ws.on_ticks = self.on_ticks
        self.kite_ws.on_connect = self.on_connect
        self.kite_ws.on_order_update = self.on_order_update
        self.kite_ws.on_close = self.on_close
        self.kite_ws.on_error = self.on_error
        self.kite_ws.on_reconnect = self.on_reconnect
        self.kite_ws.on_noreconnect = self.on_noreconnect
        self.kite_ws.connect(threaded=True)
