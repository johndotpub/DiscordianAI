import importlib
from unittest.mock import patch

import pytest


def test_main_importable():
    importlib.import_module("src.main")  # Should not raise


def test_main_runs():
    import sys

    with (
        patch("src.main.run_bot") as mock_run_bot,
        patch("src.main.load_config") as mock_load_config,
        patch("src.main.parse_arguments") as mock_parse_arguments,
    ):
        # Patch sys.argv to avoid pytest args
        sys_argv_backup = sys.argv
        sys.argv = ["prog"]
        mock_parse_arguments.return_value = type("Args", (), {"conf": None, "folder": None})()
        # Provide required configuration values
        mock_load_config.return_value = {
            "LOG_FILE": "test.log",
            "LOG_LEVEL": "INFO",
            "DISCORD_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
        }
        from src import main

        main.main()
        mock_run_bot.assert_called_once()
        sys.argv = sys_argv_backup


def test_main_handles_exception(monkeypatch):
    import sys

    from src import main

    # Patch sys.argv to avoid pytest args
    sys_argv_backup = sys.argv
    sys.argv = ["prog"]

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
            "OPENAI_API_KEY": "test_api_key",
        },
    )
    with pytest.raises(SystemExit, match="1"):
        main.main()
    sys.argv = sys_argv_backup
