"""Tests for structured logging configuration."""

from io import StringIO
import logging
import os
import re
from unittest.mock import patch

import pytest
import structlog

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
    assert any(
        isinstance(proc, structlog.stdlib.ExtraAdder)
        for proc in root.handlers[0].formatter.processors
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


def test_drop_record():
    """_drop_record removes internal record keys."""
    from src.structured_logging import _drop_record

    event = {"_record": object(), "record": object(), "msg": "hello"}
    result = _drop_record(logging.getLogger("test"), "info", event)
    assert "_record" not in result
    assert "record" not in result
    assert "msg" in result


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
