"""Regression tests for the OpenAI model generation and family allowlist."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config import (
    DEFAULT_OPENAI_MODEL,
    OPENAI_VALID_MODELS,
    is_supported_openai_model,
)
from src.health_checks import APIHealthMonitor

EXPECTED_VALID_MODELS = {
    "gpt-6-luna",
    "gpt-6.1-sol",
    "gpt-6.1-terra",
    "gpt-6-astra",
    "gpt-6-sol",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5-pro",
}


def _models_client(model_ids: list[str]) -> SimpleNamespace:
    response = SimpleNamespace(data=[SimpleNamespace(id=model_id) for model_id in model_ids])
    return SimpleNamespace(models=SimpleNamespace(list=AsyncMock(return_value=response)))


def test_default_model_is_the_current_generation():
    assert DEFAULT_OPENAI_MODEL == "gpt-6-luna"
    assert is_supported_openai_model("gpt-6-luna") is True


def test_every_documented_model_is_accepted():
    assert set(OPENAI_VALID_MODELS) == EXPECTED_VALID_MODELS

    for model in OPENAI_VALID_MODELS:
        assert is_supported_openai_model(model) is True, model


@pytest.mark.parametrize(
    "model",
    [
        "gpt-6.1-terra",
        "gpt-6-astra",
        "gpt-5.6-luna",
        "gpt-6-luna-2026-09-01",
    ],
)
def test_family_members_and_dated_snapshots_are_accepted(model):
    assert is_supported_openai_model(model) is True


@pytest.mark.parametrize(
    "model",
    [
        "gpt-5-chat",
        "gpt-7",
        "gpt6-luna",
        "claude-3",
        "",
    ],
)
def test_retired_unknown_and_malformed_models_are_rejected(model):
    assert is_supported_openai_model(model) is False


@pytest.mark.asyncio
async def test_health_check_uses_the_same_family_allowlist():
    monitor = APIHealthMonitor()
    client = _models_client(["gpt-6-luna"])

    current = await monitor.check_openai_health(client, {"GPT_MODEL": "gpt-6-luna"})
    assert current.status == "healthy"
    assert current.details["model"] == "gpt-6-luna"

    bogus = await monitor.check_openai_health(client, {"GPT_MODEL": "gpt-7-bogus"})
    assert bogus.status == "degraded"
    assert "gpt-7-bogus" in bogus.error
