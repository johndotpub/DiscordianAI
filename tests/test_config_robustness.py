"""Regression tests for configuration robustness and startup validation."""

import configparser
import logging
from pathlib import Path

import pytest

from src.api_validation import validate_discord_config
from src.config import _apply_config_defaults, load_config
from src.dependencies import BotDependencies
from src.main import validate_critical_config

REPO_ROOT = Path(__file__).resolve().parents[1]

ENV_KEYS = [
    "DISCORD_TOKEN",
    "ADDRESS",
    "ALLOWED_CHANNELS",
    "ALLOWED_CHANNEL_IDS",
    "ALLOWED_GUILDS",
    "ALLOWED_GUILD_IDS",
    "BOT_PRESENCE",
    "ACTIVITY_TYPE",
    "ACTIVITY_STATUS",
    "OPENAI_API_KEY",
    "OPENAI_API_URL",
    "PERPLEXITY_API_KEY",
    "PERPLEXITY_API_URL",
    "PERPLEXITY_MODEL",
    "GPT_MODEL",
    "INPUT_TOKENS",
    "OUTPUT_TOKENS",
    "PERPLEXITY_OUTPUT_TOKENS",
    "CONTEXT_WINDOW",
    "SYSTEM_MESSAGE",
    "RATE_LIMIT",
    "RATE_LIMIT_PER",
    "OPENAI_MAX_CONNECTIONS",
    "OPENAI_MAX_KEEPALIVE",
    "PERPLEXITY_MAX_CONNECTIONS",
    "PERPLEXITY_MAX_KEEPALIVE",
    "LOOKBACK_MESSAGES_FOR_CONSISTENCY",
    "MAX_HISTORY_PER_USER",
    "CONVERSATION_TTL_SECONDS",
    "USER_LOCK_CLEANUP_INTERVAL",
    "ENTITY_DETECTION_MIN_WORDS",
    "MAX_URLS_PER_MESSAGE",
    "MAX_TOTAL_SCRAPED_CHARS",
    "SCRAPE_DEADLINE_SECONDS",
    "LOG_FILE",
    "LOG_LEVEL",
    "DISCORDIANAI_LOG_COLOR",
    "HEALTH_ENABLED",
    "HEALTH_HOST",
    "HEALTH_PORT",
]


@pytest.fixture(autouse=True)
def isolate_config_environment(monkeypatch):
    """Keep host environment variables from leaking into these tests."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _write_config(tmp_path: Path, contents: str) -> str:
    config_path = tmp_path / "config.ini"
    config_path.write_text(contents, encoding="utf-8")
    return str(config_path)


def _minimal_config() -> dict:
    return {
        "DISCORD_TOKEN": "test-token",
        "OPENAI_API_KEY": "sk-test",
        "RATE_LIMIT": 10,
        "RATE_LIMIT_PER": 60,
        "OUTPUT_TOKENS": 8000,
        "BOT_PRESENCE": "online",
        "ACTIVITY_TYPE": "watching",
        "ALLOWED_CHANNELS": ["general"],
        "ALLOWED_CHANNEL_IDS": [],
    }


def test_malformed_health_enabled_warns_with_key_and_section(tmp_path, caplog):
    config_path = _write_config(tmp_path, "[Health]\nHEALTH_ENABLED=yes please\n")

    with caplog.at_level(logging.WARNING, logger="src.config"):
        config = load_config(config_path)

    warnings = [record.getMessage() for record in caplog.records]
    assert any("HEALTH_ENABLED" in message and "Health" in message for message in warnings)
    assert config["HEALTH_ENABLED"] is True


def test_invalid_bot_presence_is_rejected_at_startup():
    config = _minimal_config()
    config["BOT_PRESENCE"] = "Online"

    with pytest.raises(ValueError) as exc_info:
        validate_critical_config(config, logging.getLogger("test.config"))

    message = str(exc_info.value)
    assert "BOT_PRESENCE" in message
    for value in ("online", "offline", "idle", "dnd", "invisible"):
        assert value in message


def test_invalid_activity_type_is_rejected_at_startup():
    config = _minimal_config()
    config["ACTIVITY_TYPE"] = "teleporting"

    with pytest.raises(ValueError) as exc_info:
        validate_critical_config(config, logging.getLogger("test.config"))

    message = str(exc_info.value)
    assert "ACTIVITY_TYPE" in message
    for value in ("playing", "streaming", "listening", "watching", "custom", "competing"):
        assert value in message


def test_health_port_from_environment_is_honoured(monkeypatch):
    monkeypatch.setenv("HEALTH_PORT", "9123")

    config = load_config()

    assert config["HEALTH_PORT"] == 9123


def test_health_environment_overrides_are_coerced(monkeypatch):
    monkeypatch.setenv("HEALTH_ENABLED", "false")
    monkeypatch.setenv("HEALTH_HOST", "127.0.0.2")
    monkeypatch.setenv("HEALTH_PORT", "9123")

    config = load_config()

    assert config["HEALTH_ENABLED"] is False
    assert config["HEALTH_HOST"] == "127.0.0.2"
    assert config["HEALTH_PORT"] == 9123


def test_allowed_channel_ids_documented_in_sample_config():
    sample = (REPO_ROOT / "config.ini.example").read_text(encoding="utf-8")
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "config.ini.example", encoding="utf-8")

    assert "ALLOWED_CHANNEL_IDS" in sample
    assert "ALLOWED_CHANNEL_IDS" in parser["Discord"]
    assert "precedence" in sample.lower()


def test_activity_type_defaults_agree_on_watching():
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "config.ini.example", encoding="utf-8")
    sample_default = parser.get("Discord", "ACTIVITY_TYPE")

    defaults: dict = {}
    _apply_config_defaults(defaults)
    default_from_config = defaults["ACTIVITY_TYPE"]

    deps = BotDependencies(bot=object(), logger=logging.getLogger("test.config"), config={})

    assert sample_default == default_from_config == deps.activity_type == "watching"


def test_allowed_channel_ids_only_does_not_warn_about_no_channels(caplog):
    config = _minimal_config()
    config["ALLOWED_CHANNELS"] = []
    config["ALLOWED_CHANNEL_IDS"] = [123456789]

    with caplog.at_level(logging.WARNING):
        validate_critical_config(config, logging.getLogger("test.config"))

    messages = [record.getMessage() for record in caplog.records]
    assert not any("will not respond in any channels" in message for message in messages)

    issues = validate_discord_config(config)
    assert not any("will not respond in any channels" in issue for issue in issues)


def test_log_color_can_be_set_from_ini_and_env_overrides(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path, "[Logging]\nDISCORDIANAI_LOG_COLOR=false\n")

    config = load_config(config_path)
    assert config["DISCORDIANAI_LOG_COLOR"] is False

    monkeypatch.setenv("DISCORDIANAI_LOG_COLOR", "true")
    config = load_config(config_path)
    assert config["DISCORDIANAI_LOG_COLOR"] is True


def test_production_logging_uses_configured_log_colors(monkeypatch):
    from src import main

    captured = {}
    monkeypatch.setattr(main, "configure_structlog", lambda **kwargs: captured.update(kwargs))

    main.setup_production_logging(
        {"LOG_LEVEL": "INFO", "DISCORDIANAI_LOG_COLOR": False},
        logging.getLogger("test.config"),
    )

    assert captured["log_colors"] is False
