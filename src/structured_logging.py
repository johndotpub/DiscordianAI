"""Structured logging configuration using structlog.

Configures structlog with a hybrid renderer that outputs human-readable
logs to the console (for development) and JSON-structured logs when
environment variable ``DISCORDIANAI_LOG_JSON=1`` is set (for production
observability). Console color output follows TTY detection by default,
but can be forced on or off with ``DISCORDIANAI_LOG_COLOR``.

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
import sys
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


def _parse_flag(raw_value: str | None) -> bool | None:
    """Parse a tri-state boolean flag value."""
    if raw_value is None:
        return None

    normalized = raw_value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return None


def _env_flag(name: str) -> bool | None:
    """Parse a tri-state boolean environment variable."""
    return _parse_flag(os.environ.get(name))


def _stream_is_tty(stream: Any) -> bool:
    """Return whether the stream reports itself as a terminal."""
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        return False


def _resolve_colours(force_colors: bool | None, stream: Any) -> tuple[bool, str]:
    """Return whether to colour output and the reason for the decision."""
    if force_colors is not None:
        return force_colors, "forced by setting"
    if _stream_is_tty(stream):
        return True, "tty"
    return False, "disabled because the stream is not a terminal"


def configure_structlog(
    *,
    json_logs: bool | None = None,
    log_level: str | None = None,
    log_colors: bool | None = None,
    stream: Any | None = None,
) -> None:
    """Configure structlog with stdlib integration.

    Args:
        json_logs: Force JSON output. If ``None``, reads the
            ``DISCORDIANAI_LOG_JSON`` environment variable (defaults to
            ``False``).
        log_level: Set the root logger level. If ``None``, reads
            ``DISCORDIANAI_LOG_LEVEL`` (defaults to ``INFO``).
        log_colors: Force console colors on or off. If ``None``, reads the
            ``DISCORDIANAI_LOG_COLOR`` environment variable and otherwise
            enables colors only when ``stream`` is a TTY.
        stream: Optional stream for the root handler, used by tests and
            as the output target for the root logging handler.
    """
    if json_logs is None:
        json_logs = _env_flag("DISCORDIANAI_LOG_JSON") is True
    if log_level is None:
        log_level = os.environ.get("DISCORDIANAI_LOG_LEVEL", "INFO").upper()
    force_colors = log_colors
    if isinstance(force_colors, str):
        force_colors = _parse_flag(force_colors)
    if force_colors is None:
        force_colors = _env_flag("DISCORDIANAI_LOG_COLOR")

    level = getattr(logging, log_level, logging.INFO)
    shared_processors: list[Any] = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_logger_name,
        structlog.stdlib.ExtraAdder(),
        _drop_record,
    ]

    color_reason: str | None = None
    if json_logs:
        renderer = structlog.processors.JSONRenderer()
    else:
        if stream is None:
            stream = sys.stderr
        colors_enabled, color_reason = _resolve_colours(force_colors, stream)
        renderer = structlog.dev.ConsoleRenderer(colors=colors_enabled, pad_event_to=0)

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

    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    if color_reason is not None:
        logging.getLogger(__name__).debug("Log colour decision: %s", color_reason)


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
