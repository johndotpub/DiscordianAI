"""Token-budget enforcement tests for prompt construction."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.caching import response_cache
from src.message_builder import (
    TRUNCATION_MARKER,
    build_messages,
    estimate_messages_tokens,
)
from src.models import AIRequest, OpenAIConfig, PerplexityConfig
from src.openai_processing import process_openai_message
from src.perplexity_processing import process_perplexity_message
from tests.helpers import FakeResponse

CURRENT = "What did we decide in the latest turn?"


class RecordingClient:
    """Fake provider client that records the payload it receives."""

    def __init__(self, response_text: str = "Recorded response."):
        self.response_text = response_text
        self.calls: list[dict] = []
        self.chat = self.Chat(self)
        self.responses = self.Responses(self)

    class Chat:
        def __init__(self, client):
            self.client = client
            self.completions = self.Completions(client)

        class Completions:
            def __init__(self, client):
                self.client = client

            async def create(self, *_args, **kwargs):
                self.client.calls.append(kwargs)
                return FakeResponse(self.client.response_text)

    class Responses:
        def __init__(self, client):
            self.client = client

        async def create(self, *_args, **kwargs):
            self.client.calls.append(kwargs)
            return FakeResponse(self.client.response_text)


def _make_request(message: str = CURRENT, logger=None) -> AIRequest:
    user = MagicMock()
    user.id = 12345
    return AIRequest(
        message=message,
        user=user,
        conversation_manager=MagicMock(),
        logger=logger or MagicMock(),
    )


def _history(turns: int, *, body_chars: int = 90) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for index in range(turns):
        history.append(
            {
                "role": "user",
                "content": f"Q{index:03d} " + ("question " * body_chars)[:body_chars],
            }
        )
        history.append(
            {
                "role": "assistant",
                "content": f"A{index:03d} " + ("answer " * body_chars)[:body_chars],
            }
        )
    return history


@pytest.mark.asyncio
async def test_two_hundred_turn_history_is_trimmed_and_request_is_made():
    response_cache.cache.clear()
    client = RecordingClient()
    history = _history(200)
    config = OpenAIConfig(
        output_tokens=100,
        input_tokens=2000,
        context_window=200000,
    )

    result = await process_openai_message(_make_request(), history, client, config)

    assert result == "Recorded response."
    assert client.calls
    messages = client.calls[0]["messages"]
    assert estimate_messages_tokens(messages) <= 2000
    assert len(messages) < len(history) + 2


@pytest.mark.asyncio
async def test_oldest_turns_are_dropped_but_newest_turn_and_current_survive():
    response_cache.cache.clear()
    client = RecordingClient()
    history = _history(80)
    config = OpenAIConfig(
        output_tokens=50,
        input_tokens=500,
        context_window=200000,
    )

    await process_openai_message(_make_request(), history, client, config)

    messages = client.calls[0]["messages"]
    contents = [message["content"] for message in messages]
    joined = "\n".join(contents)
    assert "Q000" not in joined
    assert "Q079" in joined
    assert "A079" in joined
    assert messages[-1] == {"role": "user", "content": CURRENT}


def test_single_oversized_message_is_truncated_with_visible_marker():
    logger = MagicMock()
    oversized = "Z" * 10000

    messages = build_messages(
        "You are concise.",
        oversized,
        None,
        input_tokens=150,
        output_tokens=50,
        context_window=200000,
        logger=logger,
    )

    current = messages[-1]["content"]
    assert len(current) < len(oversized)
    assert TRUNCATION_MARKER in current
    assert estimate_messages_tokens(messages) <= 150
    assert logger.info.call_count == 1


def test_no_trimming_and_no_log_when_prompt_is_comfortably_inside_budget():
    logger = MagicMock()
    history = [
        {"role": "user", "content": "Name a novel by Frank Herbert."},
        {"role": "assistant", "content": "Dune."},
    ]

    messages = build_messages(
        "You are helpful.",
        CURRENT,
        history,
        input_tokens=120000,
        output_tokens=8000,
        context_window=128000,
        logger=logger,
    )

    assert messages == [
        {"role": "system", "content": "You are helpful."},
        *history,
        {"role": "user", "content": CURRENT},
    ]
    logger.info.assert_not_called()
    logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_low_input_tokens_changes_the_request_outcome():
    response_cache.cache.clear()
    history = _history(50)
    high_client = RecordingClient()
    low_client = RecordingClient()

    await process_openai_message(
        _make_request(),
        history,
        high_client,
        OpenAIConfig(output_tokens=100, input_tokens=100000, context_window=200000),
    )
    response_cache.cache.clear()
    await process_openai_message(
        _make_request(),
        history,
        low_client,
        OpenAIConfig(output_tokens=100, input_tokens=300, context_window=200000),
    )

    high_messages = high_client.calls[0]["messages"]
    low_messages = low_client.calls[0]["messages"]
    assert len(low_messages) < len(high_messages)
    assert estimate_messages_tokens(low_messages) <= 300


@pytest.mark.asyncio
async def test_scraped_content_counts_toward_perplexity_prompt_budget():
    response_cache.cache.clear()
    client = RecordingClient()
    scraped = "Content from https://example.com/page:\n" + ("X" * 50000)
    request = _make_request("Summarise https://example.com/page")
    config = PerplexityConfig(
        input_tokens=500,
        output_tokens=100,
        context_window=200000,
    )

    with patch(
        "src.perplexity_processing._enhance_message_with_urls",
        AsyncMock(return_value=scraped),
    ):
        result = await process_perplexity_message(request, client, config)

    assert result is not None
    call = client.calls[0]
    messages = [
        {"role": "system", "content": call["instructions"]},
        *call["input"],
    ]
    assert estimate_messages_tokens(messages) <= 500
    assert TRUNCATION_MARKER in call["input"][-1]["content"]


@pytest.mark.asyncio
async def test_context_window_conflict_warns_and_still_sends_fitting_request():
    response_cache.cache.clear()
    logger = MagicMock()
    client = RecordingClient()
    history = _history(100)
    config = OpenAIConfig(
        output_tokens=5000,
        input_tokens=10000,
        context_window=9000,
    )

    result = await process_openai_message(
        _make_request(logger=logger),
        history,
        client,
        config,
    )

    assert result == "Recorded response."
    assert client.calls
    warning_text = " ".join(
        str(argument) for call in logger.warning.call_args_list for argument in call.args
    )
    assert "INPUT_TOKENS" in warning_text
    assert "OUTPUT_TOKENS" in warning_text
    messages = client.calls[0]["messages"]
    assert estimate_messages_tokens(messages) + config.output_tokens <= config.context_window
