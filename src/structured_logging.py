"""Structured logging configuration using structlog.

Configures structlog with a hybrid renderer that outputs human-readable
logs to the console (for development) and JSON-structured logs when
environment variable ``DISCORDIANAI_LOG_JSON=1`` is set (for production
observability).

All existing ``logging.getLogger()`` calls are automatically enriched
with structlog processors via the stdlib integration layer. No changes
to calling code are required -- standard ``logger.info(...)`` calls
gain structured context transparently.

Usage::

    from src.structured_logging import configure_structlog

    configure_structlog()  # call once at startup

    # In any module:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("request completed", service="openai", duration_ms=340)
"""

import logging
import os
from typing import Any

import structlog


def _add_logger_name(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Inject the logger name (module) into the event dict."""
    record = event_dict.get("_record")
    if record is None:
        record = event_dict.get("record")
    if record and hasattr(record, "name"):
        event_dict["logger_name"] = record.name
    return event_dict


def _drop_record(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Remove internal ``_record`` / ``record`` keys before rendering."""
    event_dict.pop("_record", None)
    event_dict.pop("record", None)
    return event_dict


def configure_structlog(
    *,
    json_logs: bool | None = None,
    log_level: str | None = None,
) -> None:
    """Configure structlog with stdlib integration.

    Args:
        json_logs: Force JSON output. If ``None``, reads the
            ``DISCORDIANAI_LOG_JSON`` environment variable (defaults to
            ``False``).
        log_level: Set the root logger level. If ``None``, reads
            ``DISCORDIANAI_LOG_LEVEL`` (defaults to ``INFO``).
    """
    if json_logs is None:
        json_logs = os.environ.get("DISCORDIANAI_LOG_JSON", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
    if log_level is None:
        log_level = os.environ.get("DISCORDIANAI_LOG_LEVEL", "INFO").upper()

    level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        level=level,
        force=True,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_logger_name,
        _drop_record,
    ]

    if json_logs:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            *shared_processors,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


def get_structured_logger(name: str, **initial_context: Any) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound with initial context.

    This is the preferred way to create loggers in new code. Existing
    ``logging.getLogger()`` calls will also be enriched via the stdlib
    integration.

    Args:
        name: Logger name (typically ``__name__``).
        **initial_context: Key-value pairs bound to every log entry.

    Returns:
        A structlog ``BoundLogger`` instance.
    """
    return structlog.get_logger(name).bind(**initial_context)
