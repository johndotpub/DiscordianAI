"""Tests for structured logging configuration."""

from io import StringIO
import logging
import os
import re
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import structlog

from src.logging_adapter import get_logger_with_context
from src.structured_logging import configure_structlog, get_structured_logger

_CANARY_VALUE = "SENTINEL-VALUE-IN-FRAME-LOCALS"
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _raise_with_secret_local() -> None:
    """Raise from a frame that holds a value the renderer must not print."""
    frame_local_secret = _CANARY_VALUE
    if frame_local_secret:
        msg = "boom"
        raise RuntimeError(msg)


def test_configure_structlog_defaults():
    """Default configuration uses console renderer and INFO level."""
    configure_structlog()
    root = logging.getLogger()
    assert root.level == logging.INFO
    assert len(root.handlers) == 1
    formatter = root.handlers[0].formatter
    assert any(
        isinstance(proc, structlog.stdlib.ExtraAdder) for proc in formatter.foreign_pre_chain
    )


def test_configure_structlog_explicit_log_colors_pass_through_to_renderer():
    """An explicit log_colors argument is handed to the console renderer."""
    with patch("structlog.dev.ConsoleRenderer") as mock_renderer:
        configure_structlog(log_colors=True)

    kwargs = mock_renderer.call_args.kwargs
    assert kwargs["colors"] is True
    assert kwargs["pad_event_to"] == 0
    assert kwargs["exception_formatter"].show_locals is False


def test_configure_structlog_json_mode():
    """JSON mode can be enabled via argument."""
    configure_structlog(json_logs=True)
    root = logging.getLogger()
    assert root.level == logging.INFO
    assert len(root.handlers) == 1


def test_configure_structlog_debug_level():
    """Log level can be set via argument."""
    configure_structlog(log_level="DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1


def test_configure_structlog_env_json():
    """DISCORDIANAI_LOG_JSON=1 enables JSON mode."""
    with patch.dict(os.environ, {"DISCORDIANAI_LOG_JSON": "1"}):
        configure_structlog()
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert len(root.handlers) == 1


def test_configure_structlog_env_level():
    """DISCORDIANAI_LOG_LEVEL environment variable sets level."""
    with patch.dict(os.environ, {"DISCORDIANAI_LOG_LEVEL": "WARNING"}):
        configure_structlog()
        root = logging.getLogger()
        assert root.level == logging.WARNING
        assert len(root.handlers) == 1


def test_get_structured_logger():
    """get_structured_logger returns a bound logger."""
    configure_structlog()
    log = get_structured_logger("test", service="openai")
    assert log is not None


def test_add_logger_name_with_record():
    """_add_logger_name extracts name from a log record."""
    from src.structured_logging import _add_logger_name

    record = logging.LogRecord(
        name="test.module", level=20, pathname="", lineno=0, msg="test", args=(), exc_info=None
    )
    event = {"_record": record}
    result = _add_logger_name(logging.getLogger("test"), "info", event)
    assert result["logger_name"] == "test.module"


def test_add_logger_name_with_record_key():
    """_add_logger_name extracts name from record key (not _record)."""
    from src.structured_logging import _add_logger_name

    record = logging.LogRecord(
        name="alt.module", level=20, pathname="", lineno=0, msg="test", args=(), exc_info=None
    )
    event = {"record": record}
    result = _add_logger_name(logging.getLogger("test"), "info", event)
    assert result["logger_name"] == "alt.module"


def test_add_logger_name_no_record():
    """_add_logger_name skips when no record is present."""
    from src.structured_logging import _add_logger_name

    event = {"event": "something"}
    result = _add_logger_name(logging.getLogger("test"), "info", event)
    assert "logger_name" not in result


def test_structured_logger_binds_context():
    """Bound context is rendered into the structured log output."""
    stream = StringIO()

    configure_structlog(json_logs=True, stream=stream)
    log = get_structured_logger("test.module", request_id="abc123")
    log.info("hello world")

    output = stream.getvalue()
    assert "abc123" in output
    assert '"request_id": "abc123"' in output
    assert '"event": "hello world"' in output


@pytest.mark.parametrize(
    ("json_logs", "log_colors"),
    [(True, None), (False, True), (False, False)],
)
def test_rendered_tracebacks_never_include_frame_locals(json_logs, log_colors):
    """Coloured, plain, and JSON tracebacks keep locals out of the output."""
    stream = StringIO()

    configure_structlog(json_logs=json_logs, log_colors=log_colors, stream=stream)
    log = logging.getLogger("test.exceptions")
    try:
        _raise_with_secret_local()
    except RuntimeError:
        log.exception("rendered failure")

    output = stream.getvalue()
    plain_output = _ANSI_ESCAPE.sub("", output)
    assert _CANARY_VALUE not in output
    assert _CANARY_VALUE not in plain_output
    assert "Traceback (most recent call last)" in plain_output
    assert "RuntimeError: boom" in plain_output


def test_exception_logging_falls_back_when_rich_is_unavailable(monkeypatch):
    """A console logger without Rich renders the traceback instead of failing."""
    stream = StringIO()
    monkeypatch.setitem(sys.modules, "rich", None)

    configure_structlog(json_logs=False, log_colors=False, stream=stream)
    log = logging.getLogger("test.no_rich")
    try:
        _raise_with_secret_local()
    except RuntimeError:
        log.exception("rendered failure")

    output = stream.getvalue()
    plain_output = _ANSI_ESCAPE.sub("", output)
    assert "Logging error" not in output
    assert "NameError" not in output
    assert "Traceback (most recent call last)" in plain_output
    assert "RuntimeError: boom" in plain_output
    assert _CANARY_VALUE not in output


@pytest.mark.parametrize("json_logs", [False, True])
def test_adapter_context_ids_are_rendered(json_logs):
    """Stdlib adapter extras and the logger name reach console and JSON output."""
    stream = StringIO()
    configure_structlog(json_logs=json_logs, log_colors=False, stream=stream)
    message = SimpleNamespace(
        author=SimpleNamespace(id=987654321),
        channel=SimpleNamespace(id=123456789),
        guild=SimpleNamespace(id=555444333, name="FREE-TEXT-GUILD-NAME"),
    )

    logger = get_logger_with_context(logging.getLogger("test.adapter_render"), message)
    logger.info("hello context")

    output = stream.getvalue()
    assert "hello context" in output
    assert "user_id" in output
    assert "987654321" in output
    assert "channel_id" in output
    assert "123456789" in output
    assert "guild_id" in output
    assert "555444333" in output
    if json_logs:
        assert '"logger_name": "test.adapter_render"' in output
    else:
        assert "[test.adapter_render]" in output
    assert "FREE-TEXT-GUILD-NAME" not in output
