import os, sys
import logging
import logging.handlers


def setup_logging():
    """
    Configures and sets up a centralized logger for the trading system.

    This function initializes a logger named "system" with two handlers:
    1.  A TimedRotatingFileHandler that saves logs to a file (`logs/system.log`),
        with daily rotation. It keeps a backup of the last 7 days' logs.
        This handler logs messages at the DEBUG level and above.
    2.  A StreamHandler that outputs logs to the console. This handler
        logs messages at the INFO level and above, providing a less
        verbose output on the console compared to the log file.

    The log format includes a timestamp, logger name, log level, filename,
    line number, function name, process ID, and the log message itself.

    Returns:
        logging.Logger: The configured logger instance.
    """
    # Determine package root directory and log directory
    package_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(package_dir, "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Create the root logger for the package
    logger = logging.getLogger("system")
    logger.setLevel(logging.DEBUG)

    # Create a TimedRotatingFileHandler: a new log file every day
    log_file = os.path.join(log_dir, "system.log")
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=7
    )
    file_handler.suffix = "%Y-%m-%d"

    # Define a detailed formatter: time, logger name, level, filename:line, function, process ID, message
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - PID:%(process)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Optionally add a console handler at a higher level (e.g., INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s - PID:%(process)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    logger.debug("Logging is set up.")
    return logger


# Initialize and export the logger
logger = setup_logging()
