"""Contract tests for literal config values and fatal file errors."""

import configparser
import os
from pathlib import Path

import pytest

from src.config import ConfigFileError, load_config


@pytest.fixture(autouse=True)
def isolate_config_environment(monkeypatch):
    """Keep host environment variables from replacing file values under test."""
    for key in (
        "DISCORD_TOKEN",
        "GPT_MODEL",
        "SYSTEM_MESSAGE",
        "OPENAI_API_KEY",
        "REASONING_EFFORT",
    ):
        monkeypatch.delenv(key, raising=False)


def _write_config(tmp_path: Path, contents: str) -> Path:
    config_path = tmp_path / "config.ini"
    config_path.write_text(contents, encoding="utf-8")
    return config_path


def test_percent_signs_are_read_literally(tmp_path):
    """A prompt containing '%' loads instead of failing interpolation."""
    config_path = _write_config(
        tmp_path,
        "[Discord]\nDISCORD_TOKEN=token-value\n"
        "[Default]\nSYSTEM_MESSAGE=I am 100% sure; no %% escaping needed.\n",
    )

    config = load_config(str(config_path))

    assert config["DISCORD_TOKEN"] == "token-value"  # noqa: S105 — fixture token, not a credential
    assert config["SYSTEM_MESSAGE"] == "I am 100% sure; no %% escaping needed."


def test_duplicate_option_is_a_fatal_error_naming_the_file(tmp_path):
    """A duplicated key stops startup instead of silently using defaults."""
    config_path = _write_config(
        tmp_path,
        "[Discord]\nDISCORD_TOKEN=first\nDISCORD_TOKEN=second\n",
    )

    with pytest.raises(ConfigFileError) as exc_info:
        load_config(str(config_path))

    message = str(exc_info.value)
    assert str(config_path) in message
    assert "discord_token" in message.lower()
    assert "already exists" in message


def test_malformed_file_is_a_fatal_error_naming_the_file(tmp_path):
    """A missing section header cannot turn into a defaults-only startup."""
    config_path = _write_config(tmp_path, "[Discord\nDISCORD_TOKEN=abc\n")

    with pytest.raises(ConfigFileError) as exc_info:
        load_config(str(config_path))

    message = str(exc_info.value)
    assert str(config_path) in message
    assert isinstance(exc_info.value.__cause__, configparser.Error)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read mode-000 files")
def test_unreadable_file_is_a_fatal_error_naming_the_file(tmp_path):
    """A permission failure is reported instead of falling back to defaults."""
    config_path = _write_config(tmp_path, "[Discord]\nDISCORD_TOKEN=abc\n")
    config_path.chmod(0)

    try:
        with pytest.raises(ConfigFileError) as exc_info:
            load_config(str(config_path))
    finally:
        config_path.chmod(0o600)

    message = str(exc_info.value)
    assert str(config_path) in message
    assert "Permission denied" in message


def test_missing_explicit_file_is_a_fatal_error(tmp_path):
    """A supplied path must exist; defaults apply only when no path is given."""
    missing = tmp_path / "missing.ini"

    with pytest.raises(ConfigFileError) as exc_info:
        load_config(str(missing))

    assert str(missing) in str(exc_info.value)


def test_no_config_file_still_uses_defaults_and_environment(monkeypatch):
    """Omitting --conf remains a supported defaults-only startup."""
    monkeypatch.setenv("DISCORD_TOKEN", "env-token")

    config = load_config()

    assert config["DISCORD_TOKEN"] == "env-token"  # noqa: S105 — fixture token, not a credential
    assert config["SYSTEM_MESSAGE"] == "You are a helpful assistant."
