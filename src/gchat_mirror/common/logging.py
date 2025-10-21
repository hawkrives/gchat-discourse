# ABOUTME: Structured logging configuration utilities
# ABOUTME: Sets up structlog-based logging for the application

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog import contextvars


def configure_logging(debug: bool = False) -> None:
    """Configure structured logging with structlog."""
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    structlog.configure(
        processors=[
            contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger."""
    return structlog.get_logger(name)
