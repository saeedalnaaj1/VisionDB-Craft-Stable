"""Centralized logging configuration.

Called **once** at application startup from :func:`imagecraft.app.main`.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(
    level: int = logging.DEBUG,
    log_file: Path | None = None,
) -> None:
    """Configure the root logger with console and optional file handlers.

    Args:
        level: Logging level (e.g. ``logging.DEBUG``).
        log_file: If provided, also write logs to this file.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)-7s] %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(console)

    # File handler (optional)
    if log_file is not None:
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)-7s] %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(file_handler)

    # Quiet down noisy third-party loggers
    logging.getLogger("PIL").setLevel(logging.WARNING)
