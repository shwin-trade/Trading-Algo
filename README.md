# Python Trading Algo Framework

This repository provides a lightweight, extensible framework for developing and running algorithmic trading strategies in Python. It includes a modular architecture with support for multiple brokers, a sample trading strategy, and tools for order management and logging.

## Disclaimer

This software is provided for **educational and informational purposes only**. Trading in financial markets involves substantial risk, and you may lose all or more than your initial investment. By using this software, you acknowledge that all trading decisions are made at your own risk. The creators assume no liability for any financial losses incurred through its use. **Always do your own research and consult with a qualified financial advisor before trading.**

## Features

- **Modular Architecture**: Easily extend the framework with new brokers or strategies.
- **Multi-Broker Support**: Comes with pre-built support for Fyers (v3 API) and Zerodha (Kite Connect).
- **Live & Paper Trading Ready**: Can be used with live broker credentials.
- **Configuration Driven**: Manage strategy parameters via YAML files and command-line arguments.
- **Sample Strategy**: Includes the "Survivor" options selling strategy as a practical example.

## System Architecture

The framework is designed with a clear separation of concerns to promote modularity and ease of development.

```
+-------------------+      +---------------------+      +--------------------+
|   Broker          |      |   Data Dispatcher   |      |   Strategy         |
| (Fyers/Zerodha)   |----->| (dispatcher.py)     |----->| (survivor.py)      |
| - Fetches data    |      | - Routes data       |      | - Implements logic |
| - Executes orders |      | - Manages queue     |      | - Places orders    |
+-------------------+      +---------------------+      +--------------------+
        ^                                                        |
        |                                                        |
        +--------------------------------------------------------+
        |
+-------------------+
|   Order Tracker   |
| (orders.py)       |
| - Tracks state    |
| - Persists orders |
+-------------------+
```

### Core Components

- **`brokers/`**: Contains the broker-specific implementations.
  - **`base.py`**: An abstract base class defining the common interface for all brokers.
  - **`fyers.py`**: Implementation for Fyers API v3, including TOTP authentication, REST calls, and WebSocket handling.
  - **`zerodha.py`**: Implementation for Zerodha Kite Connect, supporting both automated and manual authentication.
- **`dispatcher.py`**: A simple data router that decouples the data source (broker WebSocket) from the data consumer (strategy). It uses a queue to channel live market data to the strategy.
- **`orders.py`**: Provides the `OrderTracker` class, which manages the state of all placed orders and persists them to a JSON file, allowing for state recovery between sessions.
- **`logger.py`**: Configures a centralized, rotating file logger and a console logger for the entire application.
- **`strategy/`**: The directory for housing trading strategies.
  - **`survivor.py`**: An example options selling strategy that trades based on NIFTY index movements.
  - **`configs/survivor.yml`**: The configuration file for the Survivor strategy.

## Setup

### 1. Install Dependencies

This project uses `uv` for fast dependency management.

First, install `uv`:
```bash
# Using curl
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or using pip
pip install uv
```

Then, sync the environment to install the required packages from `pyproject.toml`:
```bash
uv sync
```

Alternatively, if you prefer `pip`, you can generate a `requirements.txt` from `pyproject.toml` and install from it.

### 2. Configure Environment Variables

Create a `.env` file by copying the sample file:
```bash
cp .sample.env .env
```

Now, edit the `.env` file and add your broker credentials.

**For Fyers:**
```env
# Set BROKER_NAME to fyers
BROKER_NAME=fyers
BROKER_TOTP_ENABLE=true

# Your Fyers API credentials
BROKER_API_KEY=<YOUR_FYERS_API_KEY>
BROKER_API_SECRET=<YOUR_FYERS_API_SECRET>

# Your Fyers account details for TOTP login
BROKER_ID=<YOUR_FYERS_ID>
BROKER_TOTP_REDIDRECT_URI=<YOUR_FYERS_REDIRECT_URI>
BROKER_TOTP_KEY=<YOUR_TOTP_SECRET_KEY>
BROKER_TOTP_PIN=<YOUR_4_DIGIT_PIN>
```

**For Zerodha:**
```env
# Set BROKER_NAME to zerodha
BROKER_NAME=zerodha

# Set to true for automated login, false for manual request_token input
BROKER_TOTP_ENABLE=true

# Your Kite Connect API credentials
BROKER_API_KEY=<YOUR_KITE_API_KEY>
BROKER_API_SECRET=<YOUR_KITE_API_SECRET>

# Required for automated login
BROKER_ID=<YOUR_ZERODHA_USER_ID>
BROKER_PASSWORD=<YOUR_ZERODHA_PASSWORD>
BROKER_TOTP_KEY=<YOUR_TOTP_SECRET_KEY>
```

## Running the Survivor Strategy

The `survivor.py` script can be run directly. It loads its default configuration from `strategy/configs/survivor.yml`.

Navigate to the strategy directory to run it:
```bash
cd strategy/
```

### Basic Usage
This command runs the strategy using the default parameters defined in the YAML file.
```bash
python survivor.py
```

### Overriding Parameters
You can override any configuration parameter using command-line arguments.
```bash
python survivor.py \
    --symbol-initials NIFTY25JAN30 \
    --pe-gap 25 \
    --ce-gap 25 \
    --pe-quantity 50 \
    --min-price-to-sell 15
```

### Viewing Configuration
To see the final configuration (after applying defaults and overrides) without running the strategy, use `--show-config`.
```bash
python survivor.py --show-config
```

## Extending the Framework

### Adding a New Broker

1.  **Create a New Class**: Create a new file in the `brokers/` directory (e.g., `mybroker.py`). Inside, define a class `MyBroker` that inherits from `BrokerBase`.
2.  **Implement `authenticate`**: Implement the `authenticate` method with the specific logic required by your broker's API. It should handle credential management and return the necessary session object or access token.
3.  **Implement Public Methods**: Add methods for core functionalities like `place_order`, `get_quote`, `get_history`, etc. Ensure the method signatures are consistent with how they are called in the strategies.
4.  **Integrate with `connect_websocket`**: If the broker provides a WebSocket for live data, implement a method to connect to it and handle incoming messages. You can use the `DataDispatcher` to route data to the strategy.

### Adding a New Strategy

1.  **Create a Strategy File**: Add a new Python file in the `strategy/` directory (e.g., `mystrategy.py`).
2.  **Define the Strategy Class**: Create a class (e.g., `MyStrategy`) that will contain your trading logic. The `__init__` method should accept the `broker` and `order_manager` instances.
3.  **Implement `on_ticks_update`**: Create a method, typically named `on_ticks_update(self, ticks)`, which will be the main entry point for processing live data from the `DataDispatcher`.
4.  **Create a Runner Block**: In the `if __name__ == "__main__":` block of your file, add the necessary code to:
    -   Initialize your chosen broker.
    -   Set up the `DataDispatcher` and `OrderTracker`.
    -   Connect to the broker's WebSocket.
    -   Instantiate your strategy class.
    -   Run a loop to get ticks from the dispatcher and pass them to your strategy's `on_ticks_update` method.
