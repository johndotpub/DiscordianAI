"""Regression tests for provider-specific limits and truthful validation."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import main as main_module
from src.api_validation import log_validation_results, validate_full_config
from src.message_processor import _process_message_core

OPENAI_KEY = "sk-" + "a" * 32
PERPLEXITY_KEY = "pplx-" + "a" * 32


def _valid_config(**overrides):
    config = {
        "DISCORD_TOKEN": "test-token",
        "OPENAI_API_KEY": OPENAI_KEY,
        "OPENAI_API_URL": "https://api.openai.com/v1/",
        "GPT_MODEL": "gpt-5-mini",
        "PERPLEXITY_API_KEY": PERPLEXITY_KEY,
        "PERPLEXITY_API_URL": "https://api.perplexity.ai",
        "PERPLEXITY_MODEL": "perplexity/sonar",
        "INPUT_TOKENS": 120000,
        "OUTPUT_TOKENS": 8000,
        "PERPLEXITY_OUTPUT_TOKENS": 7000,
        "CONTEXT_WINDOW": 128000,
        "RATE_LIMIT": 10,
        "RATE_LIMIT_PER": 60,
        "ALLOWED_CHANNELS": ["general"],
        "ALLOWED_CHANNEL_IDS": [],
        "BOT_PRESENCE": "online",
        "ACTIVITY_TYPE": "watching",
        "SYSTEM_MESSAGE": "You are a test bot.",
        "LOG_FILE": "bot.log",
        "LOG_LEVEL": "INFO",
    }
    config.update(overrides)
    return config


def _run_main_with_config(config):
    with (
        patch("src.main.load_config", return_value=config),
        patch(
            "src.main.parse_arguments",
            return_value=SimpleNamespace(conf=None, folder=None),
        ),
        patch("src.main.run_bot") as run_bot,
    ):
        try:
            main_module.main()
        except SystemExit as exc:
            return exc.code, run_bot
    return None, run_bot


def _message():
    return SimpleNamespace(
        id=1,
        author=SimpleNamespace(id=1, name="user", mention="<@1>"),
        channel=SimpleNamespace(id=2, send=AsyncMock()),
        guild=None,
        content="Hello",
    )


@pytest.mark.asyncio
async def test_output_token_settings_are_sent_to_providers_independently():
    deps = {
        "logger": logging.getLogger("test.validation"),
        "rate_limiter": MagicMock(),
        "conversation_manager": MagicMock(),
        "client": None,
        "perplexity_client": None,
        "RATE_LIMIT": 10,
        "RATE_LIMIT_PER": 60,
        "GPT_MODEL": "gpt-5-mini",
        "PERPLEXITY_MODEL": "sonar",
        "SYSTEM_MESSAGE": "You are a test bot.",
        "OUTPUT_TOKENS": 4096,
        "PERPLEXITY_OUTPUT_TOKENS": 1024,
        "config": {},
    }
    deps["conversation_manager"].get_conversation_summary_formatted.return_value = []
    response = AsyncMock(return_value=("ok", False, None))

    with (
        patch("src.message_processor.check_rate_limit", AsyncMock(return_value=True)),
        patch("src.message_processor.get_smart_response", response),
        patch("src.message_processor.send_formatted_message", AsyncMock()),
    ):
        await _process_message_core(_message(), deps, is_dm=True)

    ai_config = response.call_args.args[3]
    assert ai_config.openai.output_tokens == 4096
    assert ai_config.perplexity.output_tokens == 1024


@pytest.mark.parametrize("key", ["OUTPUT_TOKENS", "PERPLEXITY_OUTPUT_TOKENS"])
def test_output_cap_above_documented_ceiling_aborts_startup(key):
    config = _valid_config(**{key: 128001})

    warnings, errors = validate_full_config(config)

    assert any(key in error and "128000" in error for error in errors), (warnings, errors)

    exit_code, run_bot = _run_main_with_config(config)
    assert exit_code not in (None, 0)
    run_bot.assert_not_called()


def test_small_openai_output_cap_warns_about_empty_replies_and_continues():
    config = _valid_config(OUTPUT_TOKENS=128)

    warnings, errors = validate_full_config(config)

    assert not errors, errors
    warning = next(w for w in warnings if "OUTPUT_TOKENS" in w and "512" in w)
    assert "reasoning" in warning.lower()
    assert "empty" in warning.lower()

    exit_code, run_bot = _run_main_with_config(config)
    assert exit_code is None
    run_bot.assert_called_once()


def test_unknown_perplexity_model_warns_with_known_set_and_continues():
    config = _valid_config(PERPLEXITY_MODEL="sonar-experimental")

    warnings, errors = validate_full_config(config)

    assert not errors, errors
    warning = next(w for w in warnings if "sonar-experimental" in w)
    assert "perplexity/sonar" in warning

    exit_code, run_bot = _run_main_with_config(config)
    assert exit_code is None
    run_bot.assert_called_once()


def test_validation_does_not_claim_an_unconfigured_model(caplog):
    config = _valid_config(PERPLEXITY_MODEL="sonar")

    with caplog.at_level(logging.INFO, logger="test.validation"):
        passed = log_validation_results(config, logging.getLogger("test.validation"))

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert passed is True
    assert "sonar-pro" not in messages


def test_missing_openai_key_for_configured_openai_aborts_startup():
    config = _valid_config(OPENAI_API_KEY=None)

    _warnings, errors = validate_full_config(config)
    assert any("OPENAI_API_KEY" in error for error in errors), errors

    exit_code, run_bot = _run_main_with_config(config)
    assert exit_code not in (None, 0)
    run_bot.assert_not_called()
