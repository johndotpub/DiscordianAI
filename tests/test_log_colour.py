"""Tests for the ANSI colour decision in structured logging."""

from io import StringIO
import logging
import re

import pytest

from src.structured_logging import configure_structlog

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class _TTYStream(StringIO):
    """StringIO subclass that reports itself as a terminal."""

    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """Keep the globally configured root logger isolated between tests."""
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        yield
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)


def _render(monkeypatch, stream, setting=None):
    """Configure logging for ``stream`` and return the rendered output."""
    if setting is None:
        monkeypatch.delenv("DISCORDIANAI_LOG_COLOR", raising=False)
    else:
        monkeypatch.setenv("DISCORDIANAI_LOG_COLOR", setting)

    configure_structlog(stream=stream, log_level="DEBUG")
    logging.getLogger("test.log_colour").info("hello world")
    return stream.getvalue()


def test_non_tty_stream_without_setting_renders_plain_text(monkeypatch):
    """A redirected stream is not coloured when the setting is unset."""
    output = _render(monkeypatch, StringIO())

    assert "\x1b[" not in output
    assert "hello world" in output
    assert "Log colour decision: disabled because the stream is not a terminal" in (
        _ANSI_ESCAPE.sub("", output)
    )


def test_non_tty_stream_with_setting_one_renders_colour(monkeypatch):
    """An explicit DISCORDIANAI_LOG_COLOR=1 forces colour on a pipe."""
    output = _render(monkeypatch, StringIO(), setting="1")

    assert "\x1b[" in output
    assert "hello world" in output
    assert "Log colour decision: forced by setting" in _ANSI_ESCAPE.sub("", output)


def test_tty_stream_without_setting_renders_colour(monkeypatch):
    """An unset setting keeps colour on a terminal."""
    output = _render(monkeypatch, _TTYStream())

    assert "\x1b[" in output
    assert "hello world" in output
    assert "Log colour decision: tty" in _ANSI_ESCAPE.sub("", output)


def test_tty_stream_with_setting_zero_renders_plain_text(monkeypatch):
    """An explicit DISCORDIANAI_LOG_COLOR=0 disables colour on a terminal."""
    output = _render(monkeypatch, _TTYStream(), setting="0")

    assert "\x1b[" not in output
    assert "hello world" in output
    assert "Log colour decision: forced by setting" in _ANSI_ESCAPE.sub("", output)


def test_setting_counts_as_explicit_only_when_environment_or_file_sets_it(tmp_path, monkeypatch):
    """An absent key stays automatic even though the loaded config carries a value."""
    from src.main import _log_color_is_explicit

    monkeypatch.delenv("DISCORDIANAI_LOG_COLOR", raising=False)
    assert _log_color_is_explicit(None, None) is False

    monkeypatch.setenv("DISCORDIANAI_LOG_COLOR", "1")
    assert _log_color_is_explicit(None, None) is True

    monkeypatch.delenv("DISCORDIANAI_LOG_COLOR")
    config_file = tmp_path / "config.ini"
    config_file.write_text("[Logging]\nDISCORDIANAI_LOG_COLOR=0\n", encoding="utf-8")
    assert _log_color_is_explicit(str(config_file), None) is True
    assert _log_color_is_explicit(str(tmp_path / "missing.ini"), None) is False


def test_production_logging_leaves_an_absent_setting_to_tty_detection(monkeypatch):
    """The loaded default does not turn into a forced colour setting."""
    from src import main

    captured = {}
    monkeypatch.setattr(main, "configure_structlog", lambda **kwargs: captured.update(kwargs))

    main.setup_production_logging(
        {
            "LOG_LEVEL": "INFO",
            "DISCORDIANAI_LOG_COLOR": True,
            "_LOG_COLOR_EXPLICIT": False,
        },
        logging.getLogger("test.log_colour"),
    )

    assert captured["log_colors"] is None
