"""Tests for AI service configuration models."""

from dataclasses import FrozenInstanceError

import logging

import pytest

from src.models import AIClients, AIConfig, AIRequest, OpenAIConfig, PerplexityConfig


def test_ai_request_is_frozen():
    """AIRequest should be immutable."""
    request = AIRequest("hi", object(), object(), logging.getLogger("test"))

    with pytest.raises(FrozenInstanceError):
        request.message = "changed"


def test_openai_config_defaults_and_frozen():
    """OpenAIConfig should expose defaults and be immutable."""
    config = OpenAIConfig()

    assert config.model == "gpt-5-mini"
    assert config.system_message == "You are a helpful assistant."
    assert config.output_tokens == 8000

    with pytest.raises(FrozenInstanceError):
        config.output_tokens = 1


def test_perplexity_config_defaults_and_frozen():
    """PerplexityConfig should expose defaults and be immutable."""
    config = PerplexityConfig()

    assert "current web information" in config.system_message
    assert "source URLs" in config.system_message
    assert config.output_tokens == 8000

    with pytest.raises(FrozenInstanceError):
        config.model = "other"


def test_ai_config_defaults_and_frozen():
    """AIConfig should build nested defaults and be immutable."""
    config = AIConfig()

    assert isinstance(config.openai, OpenAIConfig)
    assert isinstance(config.perplexity, PerplexityConfig)

    with pytest.raises(FrozenInstanceError):
        config.openai = OpenAIConfig(model="x")


def test_ai_clients_allows_none_clients_and_is_frozen():
    """AIClients should allow optional clients and remain immutable."""
    clients = AIClients()

    assert clients.openai is None
    assert clients.perplexity is None

    with pytest.raises(FrozenInstanceError):
        clients.openai = object()
