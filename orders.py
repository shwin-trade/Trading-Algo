import json
import os
from datetime import datetime
from logger import logger


class OrderTracker:
    """
    Manages, tracks, and persists all trading orders.

    This class is responsible for adding new orders, storing them in memory,
    and persisting them to a JSON file for state management across sessions.
    It keeps track of all orders, completed orders, and the most recent order.

    Attributes:
        orders_file (str): The file path for storing order data.
        _all_orders (dict): A dictionary holding all orders, keyed by order_id.
        _current_order (dict): The most recently added order.
        _order_ids_completed (list): A list of IDs for completed orders.
    """
    def __init__(self, orders_file='artifacts/orders_data.json'):
        """
        Initializes the OrderTracker instance.

        Args:
            orders_file (str, optional): The path to the JSON file where orders
                are stored. Defaults to 'artifacts/orders_data.json'.
        """
        self.orders_file = orders_file
        self._all_orders = {}
        self._order_ids_not_completed = []
        self._current_order = None  # Private attribute for the most recent order
        self._load_orders()         # Load orders when the manager is initialized
        self._order_ids_completed = []
        self._order_types_summary = {}

    def _load_orders(self):
        """
        Loads orders from the JSON file into the in-memory dictionary.

        If the file exists and is not empty, it loads the JSON content.
        It also sets the `_current_order` to the one with the most recent
        timestamp among the loaded orders.
        """
        # Ensure the directory exists
        os.makedirs(os.path.dirname(self.orders_file), exist_ok=True)

        if os.path.exists(self.orders_file) and os.path.getsize(self.orders_file) > 0:
            try:
                with open(self.orders_file, 'r') as f:
                    self._all_orders = json.load(f)
                logger.info(f"Loaded {len(self._all_orders)} orders from '{self.orders_file}'.")

                if self._all_orders:
                    latest_order = None
                    latest_timestamp = None
                    for order_id, order_details in self._all_orders.items():
                        if 'timestamp' in order_details:
                            current_ts = datetime.fromisoformat(order_details['timestamp'])
                            if latest_timestamp is None or current_ts > latest_timestamp:
                                latest_timestamp = current_ts
                                latest_order = order_details
                    self._current_order = latest_order
                    if self._current_order:
                        logger.info(f"Current order set to: {self._current_order.get('order_id')}")
                    else:
                        logger.info("No valid current order found among loaded orders.")
            except json.JSONDecodeError:
                logger.error(f"Error decoding JSON from '{self.orders_file}'. Starting with empty orders.")
                self._all_orders = {}
                self._current_order = None
            except Exception as e:
                logger.error(f"An unexpected error occurred while loading orders: {e}")
                self._all_orders = {}
                self._current_order = None
        else:
            logger.info(f"No existing order file found at '{self.orders_file}'. Starting fresh.")
            self._all_orders = {}
            self._current_order = None

    def _save_orders(self):
        """
        Saves the current dictionary of orders to the JSON file.

        This method is called internally whenever the state of orders changes.
        It pretty-prints the JSON for readability.
        """
        try:
            os.makedirs(os.path.dirname(self.orders_file), exist_ok=True)
            with open(self.orders_file, 'w') as f:
                json.dump(self._all_orders, f, indent=4)
            logger.info(f"Saved {len(self._all_orders)} orders to '{self.orders_file}'.")
        except IOError as e:
            logger.error(f"Error saving orders to '{self.orders_file}': {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while saving orders: {e}")

    def add_order(self, order_details: dict):
        """
        Adds a new order to the tracker and persists it.

        The order details dictionary must contain a unique 'order_id'. If a
        timestamp is not provided, the current time is added automatically.
        After adding, all orders are saved to the file.

        Args:
            order_details (dict): A dictionary containing the details of the
                order. Must include a unique 'order_id' key.
        """
        order_id = order_details.get('order_id')
        if not order_id:
            logger.error("Cannot place order: 'order_id' is missing from order_details.")
            return

        if 'timestamp' not in order_details:
            order_details['timestamp'] = datetime.now().isoformat()

        self._current_order = order_details
        logger.info(f"Order being placed: {self._current_order}")

        if order_id in self._all_orders:
            logger.warning(f"Order with ID '{order_id}' already exists. Updating existing order.")
        self._all_orders[order_id] = self._current_order
        logger.info(f"Order '{order_id}' added/updated in in-memory dictionary.")

        self._save_orders()
        logger.info("Orders saved to disk.")


    @property
    def current_order(self):
        """
        dict: The most recently placed order. Returns None if no orders exist.
        """
        return self._current_order

    @property
    def all_orders(self):
        """
        dict: A copy of all orders placed, keyed by order ID.

        A copy is returned to prevent external modification of the internal state.
        """
        return self._all_orders.copy()

    @property
    def completed_order_ids(self):
        """
        list[str]: A list of completed order IDs.
        """
        return list(self._order_ids_completed)

    @property
    def completed_orders(self):
        """
        list[dict]: A list of completed order detail dictionaries.
        """
        return [self._all_orders[oid] for oid in self._order_ids_completed if oid in self._all_orders]

    @property
    def non_completed_order_ids(self):
        """
        list[str]: A list of order IDs that have not been marked as completed.
        """
        return [oid for oid in self._all_orders if oid not in self._order_ids_completed]

    @property
    def non_completed_orders(self):
        """
        list[dict]: A list of non-completed order detail dictionaries.
        """
        return [self._all_orders[oid] for oid in self._all_orders if oid not in self._order_ids_completed]

    def get_order_by_id(self, order_id: str):
        """
        Retrieves a single order by its ID.

        Args:
            order_id (str): The unique identifier of the order.

        Returns:
            dict or None: The order dictionary if found, otherwise None.
        """
        return self._all_orders.get(order_id)

    def get_total_orders_count(self):
        """
        Returns the total number of orders being tracked.

        Returns:
            int: The total count of all orders.
        """
        return len(self._all_orders)

    def get_all_orders_as_list(self):
        """
        Returns all orders as a list of dictionaries.

        Returns:
            list[dict]: A list containing all order detail dictionaries.
        """
        return list(self._all_orders.values())
    
    def complete_order(self, order_id: str):
        """
        Marks an order as completed.

        Adds the order ID to the list of completed orders and updates the
        summary of completed order types.

        Args:
            order_id (str): The unique identifier of the order to mark as completed.

        Returns:
            bool: True if the order was found and marked as completed, False otherwise.
        """
        if order_id in self._all_orders:
            if order_id not in self._order_ids_completed:
                self._order_ids_completed.append(order_id)
                if self._all_orders[order_id]['transaction_type'] not in self._order_types_summary:
                    self._order_types_summary[self._all_orders[order_id]['transaction_type']] = 1
                else:
                    self._order_types_summary[self._all_orders[order_id]['transaction_type']] += 1
                logger.info(f"Order '{order_id}' marked as completed.")
            else:
                logger.info(f"Order '{order_id}' already marked as completed.")
            return True
        else:
            logger.error(f"Order '{order_id}' not found in the order tracker.")
            return False