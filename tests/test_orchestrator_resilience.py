"""Routing must degrade safely when history is missing or each provider fails once."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.models import AIClients, AIConfig, AIRequest
from src.routing.contracts import RouteDecision
from src.routing.lexicon import LexiconError
from src.smart_orchestrator import (
    _build_route_decision,
    _process_hybrid_mode,
    get_smart_response,
)


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
async def test_web_failure_and_local_inability_do_not_retry_perplexity(caplog):
    caplog.set_level(logging.INFO)
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
    assert any("decision holds" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_model_router_mode_raises_with_the_clef_replacement():
    from src.smart_orchestrator import get_smart_response

    request = _request("Tell me something interesting", MagicMock())
    clients = AIClients(openai=object(), perplexity=object())

    with pytest.raises(NotImplementedError, match=r"use ROUTER_MODE=clef"):
        await get_smart_response(
            request,
            [],
            clients,
            AIConfig(),
            {"ROUTER_MODE": "model"},
        )


class _WriteFailingManager:
    """History reads succeed, but every write to the store fails."""

    def get_recent_ai_service(self, conversation_key, lookback_messages=6):
        _ = (conversation_key, lookback_messages)

    def get_conversation(self, user_id=None, *, conversation_key=None):
        _ = (user_id, conversation_key)
        return []

    def add_message(self, *args, **kwargs):
        _ = (args, kwargs)
        msg = "history store unavailable"
        raise RuntimeError(msg)


@pytest.mark.asyncio
async def test_failing_history_write_still_returns_the_hybrid_answer(caplog):
    caplog.set_level(logging.WARNING, logger="src.smart_orchestrator")
    manager = _WriteFailingManager()
    request = _request("Tell me something interesting", manager)
    clients = AIClients(openai=object(), perplexity=object())

    with (
        patch(
            "src.smart_orchestrator.process_openai_message",
            new=AsyncMock(return_value="A successful local answer"),
        ),
        patch("src.smart_orchestrator.process_perplexity_message", new=AsyncMock()),
    ):
        response, _suppress, _embed = await _process_hybrid_mode(request, [], clients, AIConfig())

    assert response == "A successful local answer"
    assert any(
        "Failed to record conversation turn for g:1:c:1" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_failing_history_write_still_returns_the_openai_only_answer(caplog):
    caplog.set_level(logging.WARNING, logger="src.smart_orchestrator")
    manager = _WriteFailingManager()
    request = _request("Tell me something interesting", manager)
    clients = AIClients(openai=object(), perplexity=None)

    with patch(
        "src.smart_orchestrator.process_openai_message",
        new=AsyncMock(return_value="A successful local answer"),
    ):
        response, _suppress, _embed = await get_smart_response(request, [], clients, AIConfig())

    assert response == "A successful local answer"
    assert any(
        "Failed to record conversation turn for g:1:c:1" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_lexicon_failure_falls_back_to_a_local_answer(caplog):
    caplog.set_level(logging.ERROR, logger="src.smart_orchestrator")
    request = _request("Tell me something interesting", MagicMock())
    clients = AIClients(openai=object(), perplexity=object())
    captured = {}

    async def fake_openai(routed_request, _summary, _client, _config, **_kwargs):
        captured["routing"] = routed_request.routing
        return "A successful local answer"

    with (
        patch(
            "src.smart_orchestrator.build_router",
            side_effect=LexiconError("lexicon is missing"),
        ),
        patch("src.smart_orchestrator.process_openai_message", new=fake_openai),
        patch("src.smart_orchestrator.process_perplexity_message", new=AsyncMock()),
    ):
        response, _suppress, _embed = await get_smart_response(request, [], clients, AIConfig())

    assert response == "A successful local answer"
    assert captured["routing"].route == "local"
    errors = [
        record
        for record in caplog.records
        if record.levelno == logging.ERROR and "lexicon" in record.getMessage()
    ]
    assert len(errors) == 1


class _RaisingRouter:
    """A router that fails after startup, as an unexpected implementation bug would."""

    router_id = "broken"
    policy_version = "1"

    async def decide(self, request):
        _ = request
        msg = "router backend unavailable"
        raise RuntimeError(msg)

    def decide_sync(self, request):
        _ = request
        msg = "router backend unavailable"
        raise RuntimeError(msg)


@pytest.mark.asyncio
async def test_unexpected_router_failure_falls_back_to_the_gate(caplog):
    """A router fault reaches the deterministic gate instead of an error reply."""
    caplog.set_level(logging.ERROR, logger="src.smart_orchestrator")
    manager = MagicMock(spec=ThreadSafeConversationManager)
    manager.get_recent_ai_service.return_value = None
    manager.get_conversation.return_value = []
    request = _request("is github down", manager)
    captured = {}

    async def fake_perplexity(routed_request, _client, _config, _summary=None):
        captured["routing"] = routed_request.routing
        return "web answer", False, None

    clients = AIClients(openai=object(), perplexity=object())
    with (
        patch("src.smart_orchestrator.process_openai_message", new=AsyncMock()),
        patch("src.smart_orchestrator.process_perplexity_message", new=fake_perplexity),
    ):
        response, _suppress, _embed = await get_smart_response(
            request,
            [],
            clients,
            AIConfig(),
            {"ROUTER_MODE": "heuristic"},
            router=_RaisingRouter(),
        )

    assert response == "web answer"
    assert captured["routing"].route == "web"
    assert captured["routing"].decision_source == "fallback:router_error"
    assert any("Router failed" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_injected_router_is_reused_instead_of_rebuilt():
    """The process-wide router is not reconstructed for each message."""
    manager = MagicMock(spec=ThreadSafeConversationManager)
    manager.get_recent_ai_service.return_value = None
    manager.get_conversation.return_value = []
    request = _request("Tell me something interesting", manager)
    router = MagicMock()
    router.router_id = "gate"
    router.policy_version = "1"
    router.decide = AsyncMock(
        return_value=RouteDecision(
            route="local",
            reasons=("local:default",),
            text="Tell me something interesting",
        )
    )

    with (
        patch("src.smart_orchestrator.build_router", return_value=router) as builder,
        patch(
            "src.smart_orchestrator.process_openai_message",
            new=AsyncMock(return_value="A successful local answer"),
        ),
        patch("src.smart_orchestrator.process_perplexity_message", new=AsyncMock()),
    ):
        response, _suppress, _embed = await get_smart_response(
            request,
            [],
            AIClients(openai=object(), perplexity=object()),
            AIConfig(),
            {"ROUTER_MODE": "heuristic"},
            router=router,
        )

    assert response == "A successful local answer"
    builder.assert_not_called()
    router.decide.assert_awaited_once()


@pytest.mark.asyncio
async def test_default_router_is_built_once_per_configuration():
    """Without an injected router, the fallback construction is cached."""
    manager = MagicMock(spec=ThreadSafeConversationManager)
    manager.get_recent_ai_service.return_value = None
    manager.get_conversation.return_value = []
    request = _request("Tell me something interesting", manager)
    router = MagicMock()
    router.decide = AsyncMock(
        return_value=RouteDecision(
            route="local",
            reasons=("local:default",),
            text="Tell me something interesting",
        )
    )
    config = {"ROUTER_MODE": "heuristic"}

    with patch("src.smart_orchestrator.build_router", return_value=router) as builder:
        await _build_route_decision(request, config)
        await _build_route_decision(request, config)

    builder.assert_called_once()
    assert router.decide.await_count == 2


def _failing_chat_client(error):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=error)
    return client


def _failing_responses_client(error):
    client = MagicMock()
    client.responses.create = AsyncMock(side_effect=error)
    return client


@pytest.mark.asyncio
async def test_openai_only_mode_reports_the_classified_outage_not_a_rephrase_hint():
    """A provider outage shows the outage notice, not 'try rephrasing'."""
    import openai

    from src.config import get_error_messages
    from src.error_handling import classify_error
    from src.models import OpenAIConfig

    error = openai.InternalServerError(
        "provider down",
        response=MagicMock(status_code=500, headers={}),
        body=None,
    )
    manager = MagicMock()
    request = _request("Tell me something interesting", manager)
    clients = AIClients(
        openai=_failing_chat_client(error),
        perplexity=None,
    )

    retry_sleep = AsyncMock()
    with patch("src.error_handling.asyncio.sleep", new=retry_sleep):
        response, suppress, embed = await get_smart_response(
            request,
            [],
            clients,
            AIConfig(openai=OpenAIConfig()),
        )

    assert retry_sleep.await_count == 1
    assert response == classify_error(error).user_message
    assert response != get_error_messages()["no_response_generated"]
    assert suppress is False
    assert embed is None
    manager.add_message.assert_not_called()


@pytest.mark.asyncio
async def test_single_provider_outage_logs_one_traceback(caplog):
    """One failed provider call produces one traceback, not one per layer."""
    import openai

    from src.error_handling import classify_error
    from src.models import OpenAIConfig

    caplog.set_level(logging.DEBUG)
    error = openai.InternalServerError(
        "provider down",
        response=MagicMock(status_code=500, headers={}),
        body=None,
    )
    request = _request("Tell me something interesting", MagicMock())
    clients = AIClients(
        openai=_failing_chat_client(error),
        perplexity=None,
    )

    with patch("src.error_handling.asyncio.sleep", new=AsyncMock()):
        response, _suppress, _embed = await get_smart_response(
            request,
            [],
            clients,
            AIConfig(openai=OpenAIConfig()),
        )

    assert response == classify_error(error).user_message
    tracebacks = [record for record in caplog.records if record.exc_info]
    assert len(tracebacks) == 1


@pytest.mark.asyncio
async def test_perplexity_only_mode_reports_the_classified_outage_not_a_rephrase_hint():
    """The Perplexity-only wrapper exposes its classified failure too."""
    import openai

    from src.config import get_error_messages
    from src.error_handling import classify_error
    from src.models import PerplexityConfig

    error = openai.InternalServerError(
        "provider down",
        response=MagicMock(status_code=500, headers={}),
        body=None,
    )
    manager = MagicMock()
    request = _request("Tell me something interesting", manager)
    clients = AIClients(
        openai=None,
        perplexity=_failing_responses_client(error),
    )

    retry_sleep = AsyncMock()
    with patch("src.error_handling.asyncio.sleep", new=retry_sleep):
        response, suppress, embed = await get_smart_response(
            request,
            [],
            clients,
            AIConfig(perplexity=PerplexityConfig()),
        )

    assert retry_sleep.await_count == 1
    assert response == classify_error(error).user_message
    assert response != get_error_messages()["no_response_generated"]
    assert suppress is False
    assert embed is None
    manager.add_message.assert_not_called()
