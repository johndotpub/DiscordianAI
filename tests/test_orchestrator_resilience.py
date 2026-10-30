"""Routing must degrade safely when history is missing or each provider fails once."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.models import AIClients, AIConfig, AIRequest
from src.smart_orchestrator import _process_hybrid_mode


def _request(message, manager):
    user = MagicMock()
    user.id = 12345
    return AIRequest(
        message=message,
        user=user,
        conversation_manager=manager,
        logger=logging.getLogger("orchestrator-resilience"),
        conversation_key="g:1:c:1",
    )


@pytest.mark.asyncio
async def test_missing_conversation_manager_still_returns_the_answer(caplog):
    caplog.set_level(logging.WARNING, logger="src.smart_orchestrator")
    request = _request("Tell me something interesting", None)
    openai = AsyncMock(return_value="A successful local answer")
    perplexity = AsyncMock()
    clients = AIClients(openai=object(), perplexity=object())

    with (
        patch("src.smart_orchestrator.process_openai_message", openai),
        patch("src.smart_orchestrator.process_perplexity_message", perplexity),
    ):
        response, suppress, embed = await _process_hybrid_mode(request, [], clients, AIConfig())

    assert response == "A successful local answer"
    assert suppress is False
    assert embed is None
    openai.assert_awaited_once()
    perplexity.assert_not_awaited()
    assert any("No conversation manager" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_raising_history_lookup_logs_and_continues(caplog):
    caplog.set_level(logging.WARNING, logger="src.routing.context")
    manager = MagicMock(spec=ThreadSafeConversationManager)
    manager.get_recent_ai_service.side_effect = RuntimeError("history backend down")
    request = _request("Tell me something interesting", manager)
    openai = AsyncMock(return_value="A successful local answer")
    clients = AIClients(openai=object(), perplexity=object())

    with (
        patch("src.smart_orchestrator.process_openai_message", openai),
        patch("src.smart_orchestrator.process_perplexity_message", AsyncMock()),
    ):
        response, _suppress, _embed = await _process_hybrid_mode(request, [], clients, AIConfig())

    assert response == "A successful local answer"
    assert any("routing with empty context" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_web_failure_and_local_inability_call_each_provider_once(caplog):
    caplog.set_level(logging.WARNING, logger="src.smart_orchestrator")
    manager = MagicMock(spec=ThreadSafeConversationManager)
    manager.get_recent_ai_service.return_value = None
    request = _request("http://example.com/status", manager)
    local_answer = "Sorry, I can't access the internet to look that up."
    perplexity = AsyncMock(return_value=None)
    openai = AsyncMock(return_value=local_answer)
    clients = AIClients(openai=object(), perplexity=object())

    with (
        patch("src.smart_orchestrator.process_perplexity_message", perplexity),
        patch("src.smart_orchestrator.process_openai_message", openai),
    ):
        response, suppress, embed = await _process_hybrid_mode(request, [], clients, AIConfig())

    assert response == local_answer
    assert suppress is False
    assert embed is None
    perplexity.assert_awaited_once()
    openai.assert_awaited_once()
    assert any(
        "already failed in this request" in record.getMessage() for record in caplog.records
    )


@pytest.mark.asyncio
async def test_model_router_mode_raises_with_the_design_pointer():
    from src.smart_orchestrator import get_smart_response

    request = _request("Tell me something interesting", MagicMock())
    clients = AIClients(openai=object(), perplexity=object())

    with pytest.raises(NotImplementedError, match=r"docs/routing/DESIGN\.md"):
        await get_smart_response(
            request,
            [],
            clients,
            AIConfig(),
            {"ROUTER_MODE": "model"},
        )
