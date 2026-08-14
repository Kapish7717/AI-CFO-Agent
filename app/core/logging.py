"""Structured, rotating application logging.

Replaces the global ``basicConfig(FileHandler="cfo_backend.log")`` setup with a
size-bounded rotating file handler plus a console handler, and makes the
configuration idempotent so importing this module twice never stacks handlers.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_configured = False

DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configure_logging(level: str = "INFO", log_dir: str = "logs") -> None:
    """Configure root logging once with a console + rotating file handler."""
    global _configured

    root = logging.getLogger()
    if _configured:
        root.setLevel(level.upper())
        return

    formatter = logging.Formatter(DEFAULT_FORMAT)
    root.setLevel(level.upper())

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "cfo_backend.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        # A writable log directory is a nice-to-have; never crash on it.
        root.warning("Could not create log directory %s; logging to console only.", log_dir)

    _configured = True