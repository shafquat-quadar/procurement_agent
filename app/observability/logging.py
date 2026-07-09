"""Structured logging via structlog.

All log events are JSON-renderable and are expected to carry a `trace_id`.
Secrets must never be passed into log events; the redaction layer is applied to
any SAP/tool payloads before they reach a log call.
"""

from __future__ import annotations

import logging
import sys

import structlog

_CONFIGURED = False


def configure_logging(level: str = "info") -> None:
    """Configure structlog + stdlib logging once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str = "procurement_agent") -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)
