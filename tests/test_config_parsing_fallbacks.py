"""Operator-reachable configuration parsing fallbacks."""

import logging

import pytest

from src.config import load_config

_ENV_KEYS = (
    "DISCORDIANAI_LOG_COLOR",
    "HEALTH_ENABLED",
    "OUTPUT_TOKENS",
    "PERPLEXITY_API_KEY",
    "PERPLEXITY_API_URL",
    "PERPLEXITY_MODEL",
    "PERPLEXITY_OUTPUT_TOKENS",
)


@pytest.fixture(autouse=True)
def isolate_config_environment(monkeypatch):
    """Keep host environment variables from leaking into these tests."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _write_config(tmp_path, contents: str) -> str:
    config_path = tmp_path / "config.ini"
    config_path.write_text(contents, encoding="utf-8")
    return str(config_path)


def test_invalid_health_enabled_environment_value_is_ignored(monkeypatch, caplog):
    """An unrecognised boolean leaves the default endpoint enabled."""
    monkeypatch.setenv("HEALTH_ENABLED", "sometimes")

    with caplog.at_level(logging.WARNING, logger="src.config"):
        config = load_config()

    assert config["HEALTH_ENABLED"] is True
    assert any(
        "Invalid boolean for environment variable HEALTH_ENABLED" in record.getMessage()
        for record in caplog.records
    )


def test_explicit_perplexity_output_tokens_is_preserved(tmp_path):
    """An explicit Perplexity cap is not replaced by OUTPUT_TOKENS."""
    config_path = _write_config(
        tmp_path,
        "[Default]\nOUTPUT_TOKENS=7000\nPERPLEXITY_OUTPUT_TOKENS=1234\n",
    )

    config = load_config(config_path)

    assert config["OUTPUT_TOKENS"] == 7000
    assert config["PERPLEXITY_OUTPUT_TOKENS"] == 1234


def test_invalid_perplexity_output_tokens_falls_back_to_output_tokens(tmp_path, caplog):
    """A malformed explicit cap follows OUTPUT_TOKENS rather than a fixed figure."""
    config_path = _write_config(
        tmp_path,
        "[Default]\nOUTPUT_TOKENS=7000\nPERPLEXITY_OUTPUT_TOKENS=plenty\n",
    )

    with caplog.at_level(logging.WARNING, logger="src.config"):
        config = load_config(config_path)

    assert config["PERPLEXITY_OUTPUT_TOKENS"] == 7000
    assert any(
        "Invalid PERPLEXITY_OUTPUT_TOKENS value" in record.getMessage()
        for record in caplog.records
    )


def test_blank_perplexity_key_in_environment_keeps_the_provider_disabled(monkeypatch):
    """An explicitly blank key cannot be re-enabled by the default URL and model."""
    monkeypatch.setenv("PERPLEXITY_API_KEY", "")

    config = load_config()

    assert config["_PERPLEXITY_CONFIGURED"] is False


@pytest.mark.parametrize("key", ["OPENAI_API_URL", "GPT_MODEL"])
def test_blank_provider_environment_setting_does_not_select_the_provider(monkeypatch, key):
    """A blank environment value is unset, matching a blank value in the file."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    other_key = "GPT_MODEL" if key == "OPENAI_API_URL" else "OPENAI_API_URL"
    monkeypatch.delenv(other_key, raising=False)
    monkeypatch.setenv(key, "   ")

    config = load_config()

    assert config["_OPENAI_CONFIGURED"] is False
