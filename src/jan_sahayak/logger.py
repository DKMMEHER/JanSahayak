"""
Centralized logging configuration for Jan Sahayak.

Usage in any module:
    from jan_sahayak.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Hello from this module")
"""

import logging
import sys
from pathlib import Path

# Log format used across the entire application
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Track whether root logging has been configured (prevents duplicate handlers)
_logging_configured = False


def setup_logging(
    level: int = logging.INFO,
    log_to_file: bool = False,
    log_file_path: str = "logs/jan_sahayak.log",
) -> None:
    """
    Configure the root logger for the entire application.
    Should be called ONCE at startup (in main.py or agent.py).

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: If True, also write logs to a file
        log_file_path: Path to the log file (created if it doesn't exist)
    """
    global _logging_configured
    if _logging_configured:
        return

    # Create formatter
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_to_file:
        log_path = Path(log_file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root_logger.addHandler(file_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger for a module.

    Args:
        name: Typically __name__ of the calling module.

    Returns:
        A configured logging.Logger instance.

    Example:
        from jan_sahayak.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Processing request...")
        logger.error("Something went wrong", exc_info=True)
    """
    return logging.getLogger(name)
