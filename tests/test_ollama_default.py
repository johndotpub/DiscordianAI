"""Regression tests for the Ollama Cloud default chat provider."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import (
    DEFAULT_OPENAI_API_URL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_REASONING_EFFORT,
    is_supported_openai_model,
    load_config,
)
from src.dependencies import BotDependencies
from src.message_processor import _process_message_core
from src.openai_processing import _build_openai_api_params


def test_default_api_url_is_ollama_cloud():
    assert DEFAULT_OPENAI_API_URL == "https://ollama.com/v1/"


def test_default_model_is_deepseek():
    assert DEFAULT_OPENAI_MODEL == "deepseek-v4.1-flash:1017"


def test_default_model_passes_permissive_validation():
    assert is_supported_openai_model("deepseek-v4.1-flash:1017") is True


def test_reasoning_effort_defaults_to_high(monkeypatch):
    monkeypatch.delenv("REASONING_EFFORT", raising=False)

    config = load_config()

    assert DEFAULT_REASONING_EFFORT == "high"
    assert config["REASONING_EFFORT"] == "high"


def test_reasoning_effort_env_override_matches_gpt_model_path(monkeypatch):
    monkeypatch.setenv("REASONING_EFFORT", " low ")
    monkeypatch.setenv("GPT_MODEL", "custom-model")

    config = load_config()

    assert config["REASONING_EFFORT"] == "low"
    assert config["GPT_MODEL"] == "custom-model"


def test_empty_reasoning_effort_falls_back_to_high(monkeypatch):
    monkeypatch.setenv("REASONING_EFFORT", "   ")

    config = load_config()

    assert config["REASONING_EFFORT"] == "high"


def test_reasoning_effort_from_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("REASONING_EFFORT", raising=False)
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        "[Default]\nREASONING_EFFORT= max \n",
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config["REASONING_EFFORT"] == "max"


def test_dependency_container_exposes_reasoning_effort():
    deps = BotDependencies(bot=MagicMock(), logger=MagicMock(), config={})

    assert deps["REASONING_EFFORT"] == "high"
    assert deps.get("REASONING_EFFORT") == "high"


def test_dependency_container_accepts_a_reasoning_effort_override():
    deps = BotDependencies(
        bot=MagicMock(),
        logger=MagicMock(),
        config={},
        reasoning_effort="low",
    )

    assert deps["REASONING_EFFORT"] == "low"


@pytest.mark.asyncio
async def test_message_processor_forwards_reasoning_effort():
    deps = {
        "logger": logging.getLogger("test.ollama"),
        "rate_limiter": MagicMock(),
        "conversation_manager": MagicMock(),
        "client": None,
        "perplexity_client": None,
        "RATE_LIMIT": 10,
        "RATE_LIMIT_PER": 60,
        "GPT_MODEL": DEFAULT_OPENAI_MODEL,
        "REASONING_EFFORT": "low",
        "PERPLEXITY_MODEL": "perplexity/sonar",
        "SYSTEM_MESSAGE": "You are a test bot.",
        "OUTPUT_TOKENS": 4096,
        "PERPLEXITY_OUTPUT_TOKENS": 1024,
        "config": {},
    }
    deps["conversation_manager"].get_conversation_summary_formatted.return_value = []
    response = AsyncMock(return_value=("ok", False, None))
    message = SimpleNamespace(
        id=1,
        author=SimpleNamespace(id=1, name="user", mention="<@1>"),
        channel=SimpleNamespace(id=2, send=AsyncMock()),
        guild=None,
        content="Hello",
    )

    with (
        patch("src.message_processor.check_rate_limit", AsyncMock(return_value=True)),
        patch("src.message_processor.get_smart_response", response),
        patch("src.message_processor.send_formatted_message", AsyncMock()),
    ):
        await _process_message_core(message, deps, is_dm=True)

    ai_config = response.call_args.args[3]
    assert ai_config.openai.reasoning_effort == "low"


def test_api_params_use_max_tokens_and_reasoning_effort():
    params = _build_openai_api_params(
        "deepseek-v4.1-flash:1017",
        "You are a helpful assistant.",
        "Hello",
        1000,
        reasoning_effort="high",
    )

    assert params["max_tokens"] == 1000
    assert params["reasoning_effort"] == "high"
    assert "max_completion_tokens" not in params
