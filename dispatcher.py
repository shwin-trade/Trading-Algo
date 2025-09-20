from logger import logger

class DataDispatcher:
    """
    A simple data router for dispatching market data to a central queue.

    This class acts as a singleton-like dispatcher that decouples the data
    source (e.g., a WebSocket client) from the data consumer (e.g., a
    trading strategy). It holds a reference to a single main queue and
    provides a simple interface to register the queue and dispatch data to it.

    Attributes:
        _main_queue (queue.Queue or multiprocessing.Queue): The queue where
            data is sent.
    """

    def __init__(self):
        """
        Initializes the DataDispatcher.
        """
        self._main_queue = None
        logger.debug("DataDispatcher initialized, awaiting main queue registration.")

    def register_main_queue(self, q):
        """
        Registers the main queue for data dispatch.

        Any previously registered queue will be overwritten.

        Args:
            q (queue.Queue or multiprocessing.Queue): The queue instance to be
                used for dispatching data.
        """
        if self._main_queue is not None:
            logger.warning("Main queue is already registered. Overwriting.")
        self._main_queue = q
        logger.info("Main queue registered for DataDispatcher.")

    def dispatch(self, data):
        """
        Dispatches a data item to the registered main queue.

        If no queue has been registered, an error is logged and the
        method returns without action.

        Args:
            data (any): The data item (e.g., a market data dictionary) to be
                dispatched.
        """
        if self._main_queue is None:
            logger.error("Attempted to dispatch data, but no main queue has been registered.")
            return

        try:
            self._main_queue.put(data)
            logger.debug("Dispatched data to main queue.")
        except Exception as e:
            logger.error(f"Error dispatching data to main queue: {e}", exc_info=True)

