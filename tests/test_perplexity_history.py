"""Regression tests for conversation history on the Perplexity path."""

from unittest.mock import MagicMock

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.models import AIClients, AIConfig, AIRequest, PerplexityConfig
from src.perplexity_processing import _build_api_params, process_perplexity_message
from src.smart_orchestrator import get_smart_response
from tests.helpers import FakeResponse

HISTORY = [
    {"role": "user", "content": "Name two novels by Frank Herbert."},
    {"role": "assistant", "content": "Dune and Dune Messiah."},
    {"role": "user", "content": "When was the first one published?"},
]
CURRENT = "and what about the second one?"


class RecordingPerplexityClient:
    """Fake Perplexity client that records the payload it receives."""

    def __init__(self, response_text: str = "Recorded response.", citations=None):
        self.response_text = response_text
        self.citations = citations or []
        self.calls: list[dict] = []
        self.chat = self.Chat(self)

    class Chat:
        def __init__(self, client):
            self.client = client
            self.completions = self.Completions(client)

        class Completions:
            def __init__(self, client):
                self.client = client

            async def create(self, *_args, **kwargs):
                self.client.calls.append(kwargs)
                return FakeResponse(self.client.response_text, citations=self.client.citations)


def _make_request(
    message: str = CURRENT,
    conversation_manager=None,
    conversation_key: str | None = None,
) -> AIRequest:
    user = MagicMock()
    user.id = 12345
    return AIRequest(
        message=message,
        user=user,
        conversation_manager=conversation_manager or ThreadSafeConversationManager(),
        logger=MagicMock(),
        conversation_key=conversation_key,
    )


@pytest.mark.asyncio
async def test_perplexity_sends_full_history_with_current_message_last():
    client = RecordingPerplexityClient()
    request = _make_request()

    result = await process_perplexity_message(
        request,
        client,
        PerplexityConfig(),
        HISTORY,
    )

    assert result is not None
    messages = client.calls[0]["messages"]
    assert len(messages) == 5
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "user",
        "user",
    ]
    assert messages[1:4] == HISTORY
    assert messages[-1] == {"role": "user", "content": CURRENT}
    assert sum(message["content"] == CURRENT for message in messages) == 1


def test_openai_and_perplexity_builders_share_history_structure():
    from src.openai_processing import _build_openai_api_params

    perplexity_params = _build_api_params(
        "sonar-pro",
        "You are a helpful assistant.",
        CURRENT,
        8000,
        HISTORY,
    )
    openai_params = _build_openai_api_params(
        "gpt-5-mini",
        "You are a helpful assistant.",
        CURRENT,
        8000,
        HISTORY,
    )

    assert [message["role"] for message in perplexity_params["messages"]] == [
        message["role"] for message in openai_params["messages"]
    ]
    assert perplexity_params["messages"] == openai_params["messages"]


def test_empty_history_produces_system_and_user_only():
    expected = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": CURRENT},
    ]

    assert (
        _build_api_params("sonar-pro", "You are a helpful assistant.", CURRENT, 8000)["messages"]
        == expected
    )
    assert (
        _build_api_params("sonar-pro", "You are a helpful assistant.", CURRENT, 8000, None)[
            "messages"
        ]
        == expected
    )
    assert (
        _build_api_params("sonar-pro", "You are a helpful assistant.", CURRENT, 8000, [])[
            "messages"
        ]
        == expected
    )


@pytest.mark.asyncio
async def test_orchestrator_web_follow_up_sends_prior_turn():
    manager = ThreadSafeConversationManager()
    conversation_key = "g:1:c:2"
    manager.add_message(conversation_key, "user", "Who wrote Dune?")
    manager.add_message(
        conversation_key,
        "assistant",
        "Frank Herbert wrote Dune.",
        metadata={"ai_service": "perplexity", "model": "sonar-pro"},
    )
    conversation_summary = manager.get_conversation_summary_formatted(conversation_key)
    client = RecordingPerplexityClient("Dune Messiah was published in 1969.")
    openai_client = MagicMock()
    request = _make_request(
        message=CURRENT,
        conversation_manager=manager,
        conversation_key=conversation_key,
    )

    response, _suppress_embeds, _embed_data = await get_smart_response(
        request,
        conversation_summary,
        AIClients(openai=openai_client, perplexity=client),
        AIConfig(perplexity=PerplexityConfig()),
    )

    assert response == "Dune Messiah was published in 1969."
    assert client.calls
    messages = client.calls[0]["messages"]
    assert messages == [
        {"role": "system", "content": AIConfig().perplexity.system_message},
        {"role": "user", "content": "Who wrote Dune?"},
        {"role": "assistant", "content": "Frank Herbert wrote Dune."},
        {"role": "user", "content": CURRENT},
    ]
    openai_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_citations_still_parse_and_render_with_history():
    client = RecordingPerplexityClient(
        "The novel was published in 1965 [1].",
        ["https://example.com/dune"],
    )

    result = await process_perplexity_message(
        _make_request(),
        client,
        PerplexityConfig(),
        HISTORY,
    )

    assert result is not None
    response_text, _suppress_embeds, embed_data = result
    assert response_text == "The novel was published in 1965 [1]."
    assert "https://example.com/dune" not in response_text
    assert embed_data is not None
    assert embed_data["citations"] == {"1": "https://example.com/dune"}
    assert "[[1]](https://example.com/dune)" in embed_data["embed"].description
