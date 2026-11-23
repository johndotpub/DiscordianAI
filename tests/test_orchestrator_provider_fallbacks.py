"""Provider hand-offs inside the real smart orchestrator.

Only the provider HTTP clients are faked here; routing, history, and the
fallback branches are the production code paths.
"""

import base64
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config import ERROR_MESSAGES
from src.conversation_manager import ThreadSafeConversationManager
from src.image_attachments import ImagePayload
from src.models import AIClients, AIConfig, AIRequest
from src.smart_orchestrator import get_smart_response

CONVERSATION_KEY = "g:1:c:2"


def _image() -> ImagePayload:
    return ImagePayload(
        filename="picture.png",
        mime="image/png",
        data_b64=base64.b64encode(b"tiny-png").decode("ascii"),
        width=8,
        height=8,
    )


def _request(message: str, *, images=()) -> AIRequest:
    return AIRequest(
        message=message,
        user=SimpleNamespace(id=42),
        conversation_manager=ThreadSafeConversationManager(),
        logger=logging.getLogger("orchestrator-fallback-test"),
        conversation_key=CONVERSATION_KEY,
        images=tuple(images),
    )


def _openai_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop",
            )
        ]
    )


def _openai_client(calls: list[str], content: str) -> SimpleNamespace:
    async def create(**_kwargs):
        calls.append("openai")
        return _openai_response(content)

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=create))),
        base_url="https://api.openai.com/v1/",
    )


def _perplexity_client(calls: list[str], content: str | None) -> SimpleNamespace:
    async def create(**_kwargs):
        calls.append("perplexity")
        if content is None:
            message = "Perplexity timed out"
            raise TimeoutError(message)
        return SimpleNamespace(
            output=[
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": content}],
                }
            ],
            citations=[],
        )

    return SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=create)))


def _history(request: AIRequest) -> list[dict]:
    return request.conversation_manager.get_conversation(conversation_key=CONVERSATION_KEY)


@pytest.mark.asyncio
async def test_image_request_keeps_its_local_answer_when_it_cannot_browse():
    """A vision answer that admits web-inability is not rerouted to Perplexity."""
    calls: list[str] = []
    local_answer = "I cannot access the internet to check what is in this picture."
    request = _request("What is in this picture?", images=[_image()])
    clients = AIClients(
        openai=_openai_client(calls, local_answer),
        perplexity=_perplexity_client(calls, "A web answer that lacks the image."),
    )

    response, _suppress, _embed = await get_smart_response(
        request,
        [],
        clients,
        AIConfig(),
        {"ROUTER_MODE": "heuristic"},
    )

    assert response == local_answer
    assert calls == ["openai"]
    history = _history(request)
    assert [message["content"] for message in history] == [
        "[image: picture.png] What is in this picture?",
        local_answer,
    ]
    assert history[1]["metadata"]["ai_service"] == "openai"


@pytest.mark.asyncio
async def test_empty_chat_answer_falls_back_to_perplexity_once():
    """An empty local answer hands the same request to Perplexity exactly once."""
    calls: list[str] = []
    fallback = "The Perplexity fallback answer."
    request = _request("Tell me a joke")
    clients = AIClients(
        openai=_openai_client(calls, ""),
        perplexity=_perplexity_client(calls, fallback),
    )

    response, _suppress, _embed = await get_smart_response(
        request,
        [],
        clients,
        AIConfig(),
        {"ROUTER_MODE": "heuristic"},
    )

    assert response == fallback
    assert calls == ["openai", "perplexity"]
    history = _history(request)
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert history[1]["content"] == fallback
    assert history[1]["metadata"]["ai_service"] == "perplexity"


@pytest.mark.asyncio
async def test_both_providers_failing_records_no_history_turn():
    """The total-failure tail returns its fixed notice and records nothing."""
    calls: list[str] = []
    request = _request("Tell me a joke")
    clients = AIClients(
        openai=_openai_client(calls, ""),
        perplexity=_perplexity_client(calls, None),
    )

    response, _suppress, _embed = await get_smart_response(
        request,
        [],
        clients,
        AIConfig(),
        {"ROUTER_MODE": "heuristic"},
    )

    assert response == ERROR_MESSAGES["both_services_unavailable"]
    assert calls == ["openai", "perplexity"]
    assert _history(request) == []
