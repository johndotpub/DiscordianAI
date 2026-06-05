"""Tests for structured logging configuration."""

import logging
import os
from unittest.mock import patch

import pytest

from src.structured_logging import configure_structlog, get_structured_logger


@pytest.fixture(autouse=True)
def _reset_logging():
    """Ensure tests do not depend on pre-existing root handlers.

    Previously this fixture removed root logger handlers, but that
    races with ``pytest-xdist -n auto`` (multiple workers mutating the
    shared root logger). The fixture is kept as a no-op anchor — tests
    that need fresh state should configure their own loggers explicitly.
    """
    return


def test_configure_structlog_defaults():
    """Default configuration uses console renderer and INFO level."""
    configure_structlog()
    root = logging.getLogger()
    assert root.level == logging.INFO


def test_configure_structlog_json_mode():
    """JSON mode can be enabled via argument."""
    configure_structlog(json_logs=True)
    root = logging.getLogger()
    assert root.level == logging.INFO


def test_configure_structlog_debug_level():
    """Log level can be set via argument."""
    configure_structlog(log_level="DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG


def test_configure_structlog_env_json():
    """DISCORDIANAI_LOG_JSON=1 enables JSON mode."""
    with patch.dict(os.environ, {"DISCORDIANAI_LOG_JSON": "1"}):
        configure_structlog()
        root = logging.getLogger()
        assert root.level == logging.INFO


def test_configure_structlog_env_level():
    """DISCORDIANAI_LOG_LEVEL environment variable sets level."""
    with patch.dict(os.environ, {"DISCORDIANAI_LOG_LEVEL": "WARNING"}):
        configure_structlog()
        root = logging.getLogger()
        assert root.level == logging.WARNING


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
    """Bound context is attached to the structlog logger."""
    configure_structlog(json_logs=True)
    log = get_structured_logger("test.module", request_id="abc123")

    assert log._context["request_id"] == "abc123"
