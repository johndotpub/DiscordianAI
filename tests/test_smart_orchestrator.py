from unittest.mock import MagicMock

import pytest

from src.smart_orchestrator import (
    get_smart_response,
    has_time_sensitivity,
    is_conversational_or_creative,
    is_factual_query,
    should_use_web_search,
)


def test_has_time_sensitivity():
    assert has_time_sensitivity("What happened today?") is True
    assert has_time_sensitivity("Recent news about AI") is True
    assert has_time_sensitivity("Current market status") is True
    assert has_time_sensitivity("2025 updates") is True
    assert has_time_sensitivity("What is Python?") is False
    assert has_time_sensitivity("Tell me a joke") is False


def test_is_factual_query():
    assert is_factual_query("What is the stock price of TESLA?") is True
    assert is_factual_query("How much does it cost?") is True
    assert is_factual_query("What's the weather forecast?") is True
    assert is_factual_query("Who is the CEO of Google?") is True
    assert is_factual_query("Write me a poem") is False
    assert is_factual_query("Hello there!") is False


def test_is_conversational_or_creative():
    assert is_conversational_or_creative("Hello! How are you?") is True
    assert is_conversational_or_creative("Write me a story about robots") is True
    assert is_conversational_or_creative("What do you think about this?") is True
    assert is_conversational_or_creative("Help me code a function") is True
    assert is_conversational_or_creative("What's the meaning of life?") is True
    assert is_conversational_or_creative("What's the current stock price?") is False
    assert is_conversational_or_creative("Latest news today") is False


def test_should_use_web_search():
    # Should use web search for time-sensitive queries
    assert should_use_web_search("What's happening today?") is True

    # Should use web search for factual queries
    assert should_use_web_search("Tesla stock price") is True

    # Should NOT use web search for creative/conversational
    assert should_use_web_search("Write me a poem") is False
    assert should_use_web_search("Hello!") is False

    # Should use web search for specific entities with time sensitivity
    assert should_use_web_search("Tell me about OpenAI GPT-5 recent developments today") is True

    # Should not use web search for general coding help
    assert should_use_web_search("How to write a Python function") is False


@pytest.mark.asyncio
async def test_get_smart_response_openai_only():
    mock_user = MagicMock()
    mock_user.id = 1
    conversation_history = {}
    conversation_summary = []
    logger = MagicMock()

    # Mock OpenAI client that returns a response
    class FakeOpenAIClient:
        pass

    async def mock_process_openai_message(*args, **kwargs):
        return "OpenAI response"

    # Patch the import (in real tests you'd use proper mocking)
    import src.smart_orchestrator

    original_process_openai = src.smart_orchestrator.process_openai_message
    src.smart_orchestrator.process_openai_message = mock_process_openai_message

    try:
        response, suppress_embeds = await get_smart_response(
            "Hello!",
            mock_user,
            conversation_summary,
            conversation_history,
            logger,
            FakeOpenAIClient(),  # OpenAI client provided
            None,  # No Perplexity client
            "gpt-5",
            "You are helpful",
            8000,
        )

        assert response == "OpenAI response"
        assert suppress_embeds is False
    finally:
        src.smart_orchestrator.process_openai_message = original_process_openai


@pytest.mark.asyncio
async def test_get_smart_response_perplexity_only():
    mock_user = MagicMock()
    mock_user.id = 2
    conversation_history = {}
    conversation_summary = []
    logger = MagicMock()

    class FakePerplexityClient:
        pass

    async def mock_process_perplexity_message(*args, **kwargs):
        return ("Perplexity response with citations", True)

    # Patch the import
    import src.smart_orchestrator

    original_process_perplexity = src.smart_orchestrator.process_perplexity_message
    src.smart_orchestrator.process_perplexity_message = mock_process_perplexity_message

    try:
        response, suppress_embeds = await get_smart_response(
            "What's the latest news?",
            mock_user,
            conversation_summary,
            conversation_history,
            logger,
            None,  # No OpenAI client
            FakePerplexityClient(),  # Perplexity client provided
            "gpt-5",
            "You are helpful",
            8000,
        )

        assert response == "Perplexity response with citations"
        assert suppress_embeds is True
    finally:
        src.smart_orchestrator.process_perplexity_message = original_process_perplexity


@pytest.mark.asyncio
async def test_get_smart_response_no_clients():
    mock_user = MagicMock()
    conversation_history = {}
    conversation_summary = []
    logger = MagicMock()

    response, suppress_embeds = await get_smart_response(
        "Hello!",
        mock_user,
        conversation_summary,
        conversation_history,
        logger,
        None,  # No OpenAI client
        None,  # No Perplexity client
        "gpt-5",
        "You are helpful",
        8000,
    )

    assert "AI services are not properly configured" in response
    assert suppress_embeds is False
