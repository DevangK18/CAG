"""Root logger set-up shared by the orchestrator and its worker processes."""

import logging
import sys
from typing import Optional

LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(log_file: Optional[str], debug: bool = False) -> None:
    """Console (INFO) and, when given, the run's log file (DEBUG) on the root logger."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root_logger.addHandler(console_handler)

    if log_file:
        # Plain file handler: size-based rotation split long runs across files.
        # Worker processes append to the same file.
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers unless debug mode
    if not debug:
        for name in ("docling", "urllib3", "pdfminer", "PIL", "httpx", "asyncio"):
            logging.getLogger(name).setLevel(logging.WARNING)
