"""Tests for dependency checking module."""

from unittest.mock import MagicMock, patch

import pytest

from src.dependency_check import check_dependencies, main


class TestDependencyCheck:
    """Tests for check_dependencies function."""

    def test_check_dependencies_all_present(self):
        """Test that check_dependencies returns success when all deps are present."""
        success, missing = check_dependencies()
        # All our dependencies should be installed in the test environment
        assert success is True
        assert missing == []

    def test_check_dependencies_missing_package(self):
        """Test that check_dependencies detects missing packages."""
        with patch("builtins.__import__") as mock_import:

            def side_effect(name, *args, **kwargs):
                if name == "discord":
                    msg = "No module named 'discord'"
                    raise ImportError(msg)
                return MagicMock()

            mock_import.side_effect = side_effect
            success, missing = check_dependencies()
            assert success is False
            assert "discord.py" in missing


class TestDependencyCheckMain:
    """Tests for main function."""

    def test_main_success(self):
        """Test main function when all dependencies are present."""
        with patch("src.dependency_check.check_dependencies") as mock_check:
            mock_check.return_value = (True, [])
            result = main()
            assert result == 0

    def test_main_failure(self):
        """Test main function when dependencies are missing."""
        with patch("src.dependency_check.check_dependencies") as mock_check:
            mock_check.return_value = (False, ["missing-package"])
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
