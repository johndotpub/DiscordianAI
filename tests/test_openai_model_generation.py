"""Regression tests for the permissive OpenAI-compatible model policy."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config import DEFAULT_OPENAI_MODEL, is_supported_openai_model
from src.health_checks import APIHealthMonitor


def _models_client(model_ids: list[str]) -> SimpleNamespace:
    response = SimpleNamespace(data=[SimpleNamespace(id=model_id) for model_id in model_ids])
    return SimpleNamespace(models=SimpleNamespace(list=AsyncMock(return_value=response)))


def test_default_model_is_the_ollama_cloud_model():
    assert DEFAULT_OPENAI_MODEL == "deepseek-v4.1-flash:1017"
    assert is_supported_openai_model("deepseek-v4.1-flash:1017") is True


@pytest.mark.parametrize(
    "model",
    [
        "deepseek-v4.1-flash:1017",
        "gpt-6-luna",
        "gpt-6.1-terra",
        "gpt-6-luna-2026-09-01",
        "claude-3",
        "llama3.2:latest",
        "some-provider/model@2026",
    ],
)
def test_any_non_empty_model_identifier_is_accepted(model):
    assert is_supported_openai_model(model) is True


@pytest.mark.parametrize("model", [None, "", "   ", "\n\t "])
def test_empty_and_whitespace_models_are_rejected(model):
    assert is_supported_openai_model(model) is False


@pytest.mark.asyncio
async def test_health_check_accepts_any_non_empty_model():
    monitor = APIHealthMonitor()
    client = _models_client(["deepseek-v4.1-flash:1017"])

    current = await monitor.check_openai_health(client, {"GPT_MODEL": "deepseek-v4.1-flash:1017"})
    assert current.status == "healthy"
    assert current.details["model"] == "deepseek-v4.1-flash:1017"

    other = await monitor.check_openai_health(client, {"GPT_MODEL": "gpt-7-bogus"})
    assert other.status == "healthy"
    assert other.details["model"] == "gpt-7-bogus"


@pytest.mark.asyncio
async def test_health_check_still_flags_an_empty_model():
    monitor = APIHealthMonitor()
    client = _models_client(["deepseek-v4.1-flash:1017"])

    result = await monitor.check_openai_health(client, {"GPT_MODEL": ""})

    assert result.status == "degraded"
    assert "may be deprecated or unsupported" in result.error
