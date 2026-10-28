"""Contract tests for the deprecated LOG_FILE compatibility setting."""

from io import StringIO
import logging
from pathlib import Path
import re

import pytest

from src import main as main_module

_LOG_FILE_CLAIM = re.compile(
    r"LOG_FILE[^\n]{0,200}"
    r"(?:log file path|log path|written to|logs? (?:are )?written|log destination)",
    re.IGNORECASE,
)


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


def _capture_startup(monkeypatch):
    """Point production logging at an in-memory stream and return it."""
    stream = StringIO()
    configure = main_module.configure_structlog

    def capture_configure(**kwargs):
        kwargs["stream"] = stream
        configure(**kwargs)

    monkeypatch.setattr(main_module, "configure_structlog", capture_configure)
    return stream


def _startup_output(monkeypatch, config):
    stream = _capture_startup(monkeypatch)
    main_module.setup_production_logging(config, logging.getLogger("test.log_file_contract"))
    return stream.getvalue()


def _log_file_lines(output):
    return [line for line in output.splitlines() if "LOG_FILE" in line]


def test_log_file_set_logs_one_explanation_and_creates_no_file(tmp_path, monkeypatch):
    log_path = tmp_path / "bot.log"

    output = _startup_output(monkeypatch, {"LOG_LEVEL": "INFO", "LOG_FILE": str(log_path)})

    lines = _log_file_lines(output)
    assert len(lines) == 1
    line = lines[0]
    assert "info" in line.lower()
    assert str(log_path) in line
    assert "ignored" in line.lower()
    assert "stdout" in line.lower()
    assert not log_path.exists()


def test_log_file_unset_emits_no_explanation(monkeypatch):
    output = _startup_output(monkeypatch, {"LOG_LEVEL": "INFO"})

    assert _log_file_lines(output) == []


def test_configuration_keeps_exactly_one_root_handler(monkeypatch):
    _startup_output(monkeypatch, {"LOG_LEVEL": "INFO", "LOG_FILE": "bot.log"})

    assert len(logging.getLogger().handlers) == 1


def test_docs_do_not_claim_log_file_is_the_log_destination():
    repo_root = Path(__file__).resolve().parents[1]

    for relative_path in ("docs/Configuration.md", "README.md"):
        text = (repo_root / relative_path).read_text(encoding="utf-8")
        assert not _LOG_FILE_CLAIM.search(
            text
        ), f"{relative_path} still presents LOG_FILE as the log destination"
