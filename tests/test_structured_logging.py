"""Tests for structured logging configuration."""

import logging
import os
from unittest.mock import patch

import pytest

from src.structured_logging import configure_structlog, get_structured_logger


@pytest.fixture(autouse=True)
def _reset_logging():
    """Reset root logger handlers between tests."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    yield
    for handler in root.handlers[:]:
        root.removeHandler(handler)


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


def test_structured_logger_binds_context():
    """Bound context appears in log output."""
    configure_structlog(json_logs=True)
    log = get_structured_logger("test.module", request_id="abc123")

    import io

    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)

    log.info("test message")
    output = buffer.getvalue()
    assert "request_id" in output
    assert "abc123" in output
