import pytest
from unittest.mock import patch
import importlib


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
        mock_load_config.return_value = {"LOG_FILE": "test.log", "LOG_LEVEL": "INFO"}
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
    monkeypatch.setattr(main, "run_bot", lambda config: (_ for _ in ()).throw(Exception("fail")))
    with pytest.raises(Exception, match="fail"):
        main.main()
    sys.argv = sys_argv_backup
