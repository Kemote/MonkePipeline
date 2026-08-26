"""Central logging setup shared by every module in the pipeline.

All modules log through the same named logger ("mainMonkeLogger") so a
single call to configure_logging() wires up handlers (console + a rotating
file in the system temp dir) for the whole addon at once.
"""

import logging
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "mainMonkeLogger"
LOG_FILE = Path(tempfile.gettempdir()) / "monke_pipeline" / "monke_pipeline.log"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the shared pipeline logger, or a named child of it.

    Modules should do `logger = get_logger(__name__)` instead of calling
    logging.getLogger("mainMonkeLogger") directly, so nested log records
    show which module they came from while still routing through the same
    handlers.
    """
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")


def configure_logging(level: int = logging.DEBUG) -> logging.Logger:
    """Attach a console handler and a rotating file handler to the shared
    pipeline logger. Safe to call more than once - only wires handlers on
    the first call so re-importing this module (e.g. Blender addon reload)
    doesn't duplicate log lines."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s", "%H:%M:%S"
    )

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
