import importlib
import logging
import sys
from unittest.mock import patch

import pytest


def test_main_importable():
    main = importlib.import_module("src.main")  # Should not raise
    assert callable(main.main)
    assert callable(main.run_bot)


def test_main_runs(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "argv", ["prog"])

    with (
        patch("src.main.run_bot") as mock_run_bot,
        patch("src.main.load_config") as mock_load_config,
        patch("src.main.parse_arguments") as mock_parse_arguments,
    ):
        mock_parse_arguments.return_value = type("Args", (), {"conf": None, "folder": None})()
        # Provide required configuration values
        mock_load_config.return_value = {
            "LOG_FILE": "test.log",
            "LOG_LEVEL": "INFO",
            "DISCORD_TOKEN": "test_token",
            "OPENAI_API_KEY": "sk-" + "a" * 32,
        }
        from src import main

        main.main()
        mock_run_bot.assert_called_once()


@pytest.mark.parametrize("config_kind", ["missing", "directory"])
def test_main_rejects_a_config_path_that_is_not_a_file(monkeypatch, tmp_path, config_kind):
    import sys

    from src import main

    config_path = tmp_path / "config.ini"
    if config_kind == "directory":
        config_path.mkdir()
    monkeypatch.setattr(sys, "argv", ["prog", "--conf", str(config_path)])

    with (
        patch("src.main.load_config") as mock_load_config,
        patch("src.main.run_bot") as mock_run_bot,
        pytest.raises(SystemExit) as exc_info,
    ):
        main.main()

    assert exc_info.value.code == 1
    mock_load_config.assert_not_called()
    mock_run_bot.assert_not_called()


def test_main_handles_exception(monkeypatch):
    import sys

    from src import main

    monkeypatch.setattr(sys, "argv", ["prog"])

    def _raise_fail(_config):
        msg = "fail"
        raise Exception(msg)

    monkeypatch.setattr(main, "run_bot", _raise_fail)
    # Mock the load_config to return valid config
    monkeypatch.setattr(
        main,
        "load_config",
        lambda *_, **__: {
            "LOG_FILE": "test.log",
            "LOG_LEVEL": "INFO",
            "DISCORD_TOKEN": "test_token",
            "OPENAI_API_KEY": "sk-" + "a" * 32,
        },
    )
    with pytest.raises(SystemExit, match="1"):
        main.main()


def test_fatal_bot_run_error_is_logged_once(monkeypatch, caplog):
    """A fatal error after dependency wiring propagates to one CRITICAL record."""
    from types import SimpleNamespace

    from src import bot as bot_module, main

    logger = logging.getLogger("test.fatal-bot")
    deps = SimpleNamespace(logger=logger)

    class _FailingManager:
        def __init__(self, _deps):
            pass

        def run(self):
            msg = "boom"
            raise RuntimeError(msg)

    monkeypatch.setattr(bot_module, "initialize_bot_and_dependencies", lambda _config: deps)
    monkeypatch.setattr(bot_module, "DiscordBotManager", _FailingManager)
    monkeypatch.setattr(main, "parse_arguments", lambda: SimpleNamespace(conf=None, folder=None))
    monkeypatch.setattr(main, "load_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(main, "setup_early_logging", lambda: logger)
    monkeypatch.setattr(main, "setup_production_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "validate_critical_config", lambda *_args, **_kwargs: None)

    with (
        patch("src.api_validation.log_validation_results", return_value=True),
        caplog.at_level(logging.CRITICAL),
        pytest.raises(SystemExit) as exc_info,
    ):
        main.main()

    assert exc_info.value.code == 1
    fatal = [
        record.getMessage() for record in caplog.records if "Fatal error" in record.getMessage()
    ]
    assert len(fatal) == 1, fatal


def test_handle_unhandled_keyboard_interrupt_is_clean(monkeypatch):
    from unittest.mock import Mock

    from src.main import handle_unhandled_exception

    logger = logging.getLogger("test.keyboardinterrupt")
    logger.addHandler(logging.NullHandler())

    ex_hook = Mock()
    monkeypatch.setattr(sys, "__excepthook__", ex_hook)

    handle_unhandled_exception(KeyboardInterrupt, KeyboardInterrupt(), None, logger)

    ex_hook.assert_not_called()


def test_setup_production_logging_keeps_single_root_handler():
    from src.main import setup_production_logging

    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        root.handlers[:] = []

        setup_production_logging(
            {"LOG_LEVEL": "INFO", "LOG_FILE": "test.log"}, logging.getLogger("test")
        )

        assert len(root.handlers) == 1
    finally:
        root.handlers[:] = original_handlers
