"""Contract tests for literal config values and fatal file errors."""

import os
from pathlib import Path
import sys

import pytest

from src.config import (
    DEFAULT_OPENAI_API_URL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PERPLEXITY_API_URL,
    DEFAULT_PERPLEXITY_MODEL,
    ConfigFileError,
    load_config,
)
from src.openai_processing import _build_openai_api_params


@pytest.fixture(autouse=True)
def isolate_config_environment(monkeypatch):
    """Keep host environment variables from replacing file values under test."""
    for key in (
        "DISCORD_TOKEN",
        "GPT_MODEL",
        "SYSTEM_MESSAGE",
        "OPENAI_API_KEY",
        "OPENAI_API_URL",
        "PERPLEXITY_API_KEY",
        "PERPLEXITY_API_URL",
        "PERPLEXITY_MODEL",
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
    assert message == (
        f"Could not read configuration file {config_path}: DuplicateOptionError at line 3"
    )
    assert exc_info.value.__cause__ is None


def test_malformed_file_is_a_fatal_error_naming_the_file(tmp_path):
    """A missing section header cannot turn into a defaults-only startup."""
    config_path = _write_config(tmp_path, "[Discord\nDISCORD_TOKEN=abc\n")

    with pytest.raises(ConfigFileError) as exc_info:
        load_config(str(config_path))

    message = str(exc_info.value)
    assert message == (
        f"Could not read configuration file {config_path}: MissingSectionHeaderError at line 1"
    )
    assert exc_info.value.__cause__ is None


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
    assert message == f"Could not read configuration file {config_path}: PermissionError"
    assert exc_info.value.__cause__ is None


def test_missing_explicit_file_is_a_fatal_error(tmp_path):
    """A supplied path must exist; defaults apply only when no path is given."""
    missing = tmp_path / "missing.ini"

    with pytest.raises(ConfigFileError) as exc_info:
        load_config(str(missing))

    assert str(exc_info.value) == (
        f"Could not read configuration file {missing}: FileNotFoundError"
    )
    assert exc_info.value.__cause__ is None


def test_malformed_file_secret_is_absent_from_the_fatal_startup_log(monkeypatch, tmp_path, capsys):
    """The fatal log names the file, error class, and line without the raw line."""
    secret = "FAKE-CONFIG-SECRET-CANARY-123"  # noqa: S105 — fixture value, not a credential
    config_path = _write_config(tmp_path, f"{secret}=not-a-real-token\n")
    monkeypatch.setattr(sys, "argv", ["discordianai", "--conf", str(config_path)])

    from src import main

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    logged = captured.out + captured.err
    assert secret not in logged
    assert "MissingSectionHeaderError" in logged
    assert "line 1" in logged


def test_blank_models_and_urls_use_the_documented_defaults(tmp_path):
    """An empty non-secret string is unset, not an empty provider setting."""
    config_path = _write_config(
        tmp_path,
        "[Default]\n"
        "OPENAI_API_URL=\n"
        "GPT_MODEL=\n"
        "PERPLEXITY_API_URL=\n"
        "PERPLEXITY_MODEL=\n",
    )

    config = load_config(str(config_path))

    assert config["OPENAI_API_URL"] == DEFAULT_OPENAI_API_URL
    assert config["GPT_MODEL"] == DEFAULT_OPENAI_MODEL
    assert config["PERPLEXITY_API_URL"] == DEFAULT_PERPLEXITY_API_URL
    assert config["PERPLEXITY_MODEL"] == DEFAULT_PERPLEXITY_MODEL


def test_blank_environment_urls_and_models_use_defaults(monkeypatch):
    """The same empty-means-unset rule applies to environment overrides."""
    for key, value in (
        ("OPENAI_API_URL", ""),
        ("GPT_MODEL", "   "),
        ("PERPLEXITY_API_URL", ""),
        ("PERPLEXITY_MODEL", ""),
    ):
        monkeypatch.setenv(key, value)

    config = load_config()

    assert config["OPENAI_API_URL"] == DEFAULT_OPENAI_API_URL
    assert config["GPT_MODEL"] == DEFAULT_OPENAI_MODEL
    assert config["PERPLEXITY_API_URL"] == DEFAULT_PERPLEXITY_API_URL
    assert config["PERPLEXITY_MODEL"] == DEFAULT_PERPLEXITY_MODEL


def test_blank_reasoning_effort_in_file_omits_the_parameter(tmp_path):
    """REASONING_EFFORT is the documented exception: blank means omit."""
    config_path = _write_config(tmp_path, "[Default]\nREASONING_EFFORT=\n")

    config = load_config(str(config_path))

    assert config["REASONING_EFFORT"] == ""
    params = _build_openai_api_params(
        "model",
        "system",
        "hello",
        1024,
        reasoning_effort=config["REASONING_EFFORT"],
    )
    assert "reasoning_effort" not in params


def test_blank_provider_key_still_disables_the_provider(tmp_path):
    """A blank API key keeps its documented explicit-disable meaning."""
    config_path = _write_config(
        tmp_path,
        "[Default]\nOPENAI_API_KEY=\nPERPLEXITY_API_KEY=\n",
    )

    config = load_config(str(config_path))

    assert config["OPENAI_API_KEY"] == ""
    assert config["PERPLEXITY_API_KEY"] == ""
    assert config["_OPENAI_CONFIGURED"] is False
    assert config["_PERPLEXITY_CONFIGURED"] is False


def test_no_config_file_still_uses_defaults_and_environment(monkeypatch):
    """Omitting --conf remains a supported defaults-only startup."""
    monkeypatch.setenv("DISCORD_TOKEN", "env-token")

    config = load_config()

    assert config["DISCORD_TOKEN"] == "env-token"  # noqa: S105 — fixture token, not a credential
    assert config["SYSTEM_MESSAGE"] == "You are a helpful assistant."
