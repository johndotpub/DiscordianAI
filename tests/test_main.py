import pytest
from unittest.mock import patch
import importlib


def test_main_importable():
    importlib.import_module("src.main")  # Should not raise


def test_main_runs():
    with (
        patch("src.main.run_bot") as mock_run_bot,
        patch("src.main.load_config"),
        patch("src.main.parse_arguments") as mock_parse_arguments,
    ):
        mock_parse_arguments.return_value = type("Args", (), {"conf": None, "folder": None})()
        from src import main

        main.main()
        mock_run_bot.assert_called_once()


def test_main_handles_exception(monkeypatch):
    from src import main

    monkeypatch.setattr(main, "run_bot", lambda config: (_ for _ in ()).throw(Exception("fail")))
    with pytest.raises(Exception, match="fail"):
        main.main()
