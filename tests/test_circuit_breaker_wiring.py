"""Regression tests for provider circuit-breaker wiring.

These tests exercise the breakers as production code uses them: one breaker
per provider, wrapping the whole retry sequence for a single logical call.
"""

import asyncio
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from src.caching import request_deduplicator, response_cache
from src.config import get_error_messages
from src.error_handling import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    RetryConfig,
    classify_error,
    get_circuit_breaker,
    get_circuit_breaker_states,
    retry_with_backoff,
)
from src.models import AIClients, AIConfig, AIRequest, OpenAIConfig
from src.openai_processing import process_openai_message
from src.smart_orchestrator import _process_hybrid_mode, _process_openai_only_mode


def _request(message: str) -> AIRequest:
    user = MagicMock()
    user.id = 12345
    return AIRequest(
        message=message,
        user=user,
        conversation_manager=MagicMock(),
        logger=logging.getLogger(__name__),
    )


def _mock_response(status_code: int = 500) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        headers={},
        request=SimpleNamespace(),
    )


def _server_error() -> openai.InternalServerError:
    return openai.InternalServerError(
        "provider is down",
        response=_mock_response(),
        body=None,
    )


def _failing_client() -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=_server_error())
    return client


def _perplexity_client(text: str) -> MagicMock:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        citations=[],
        search_results=[],
    )
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


@pytest.fixture(autouse=True)
def _reset_state():
    response_cache.cache.clear()
    request_deduplicator._pending_requests.clear()


@pytest.mark.asyncio
async def test_five_failures_open_breaker_and_sixth_fails_fast():
    breaker = get_circuit_breaker("openai")
    client = _failing_client()

    with patch("src.error_handling.asyncio.sleep", new=AsyncMock()):
        for attempt in range(5):
            assert (
                await process_openai_message(
                    _request(f"failing request {attempt}"),
                    [],
                    client,
                    OpenAIConfig(),
                )
                is None
            )

    assert breaker.state == "OPEN"
    assert breaker.failure_count == 5

    client.chat.completions.create.reset_mock()
    started_at = time.monotonic()
    result = await process_openai_message(
        _request("circuit is now open"),
        [],
        client,
        OpenAIConfig(),
    )
    elapsed = time.monotonic() - started_at

    assert result is None
    assert elapsed < 0.05
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_retries_inside_one_logical_call_count_as_one_failure():
    breaker = get_circuit_breaker("openai")
    attempts = 0

    async def always_fails():
        nonlocal attempts
        attempts += 1
        raise _server_error()

    retry_config = RetryConfig(max_attempts=3, base_delay=0.0, jitter=False)

    with patch("src.error_handling.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(openai.InternalServerError):
            await breaker.call(retry_with_backoff, always_fails, retry_config, MagicMock())

    assert attempts == 3
    assert breaker.failure_count == 1
    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_half_open_admits_only_one_probe():
    breaker = CircuitBreaker(failure_threshold=1, timeout=60)
    breaker.state = "OPEN"
    breaker.last_failure_time = time.monotonic() - 61
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def probe():
        probe_started.set()
        await release_probe.wait()
        return "recovered"

    probe_task = asyncio.create_task(breaker.call(probe))
    await asyncio.wait_for(probe_started.wait(), timeout=1.0)

    assert breaker.state == "HALF_OPEN"
    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call(probe)

    release_probe.set()
    assert await asyncio.wait_for(probe_task, timeout=1.0) == "recovered"
    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_successful_probe_closes_breaker_and_normal_calls_resume():
    breaker = CircuitBreaker(failure_threshold=2, timeout=60)
    breaker.state = "OPEN"
    breaker.failure_count = 2
    breaker.last_failure_time = time.monotonic() - 61

    async def recovered_call():
        return "ok"

    assert await breaker.call(recovered_call) == "ok"
    assert breaker.state == "CLOSED"
    assert breaker.failure_count == 0

    assert await breaker.call(recovered_call) == "ok"


@pytest.mark.asyncio
async def test_failed_probe_reopens_breaker_and_restarts_timer():
    breaker = CircuitBreaker(failure_threshold=1, timeout=60)
    breaker.state = "OPEN"
    breaker.last_failure_time = time.monotonic() - 61
    previous_failure_time = breaker.last_failure_time

    async def still_broken():
        msg = "still down"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="still down"):
        await breaker.call(still_broken)

    assert breaker.state == "OPEN"
    assert breaker.last_failure_time > previous_failure_time

    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call(still_broken)


@pytest.mark.asyncio
async def test_open_openai_breaker_falls_back_without_raising():
    breaker = get_circuit_breaker("openai")
    breaker.state = "OPEN"
    breaker.last_failure_time = time.monotonic()
    openai_client = _failing_client()

    result = await process_openai_message(
        _request("openai is broken"),
        [],
        openai_client,
        OpenAIConfig(),
    )

    assert result is None
    openai_client.chat.completions.create.assert_not_called()
    assert (
        classify_error(CircuitBreakerOpenError("openai")).user_message
        == get_error_messages()["ai_service_unavailable"]
    )

    response, _, _ = await _process_openai_only_mode(
        _request("openai is broken"),
        [],
        openai_client,
        AIConfig(openai=OpenAIConfig()),
    )
    assert response == get_error_messages()["ai_service_unavailable"]

    perplexity_client = _perplexity_client("Perplexity fallback")
    with patch("src.smart_orchestrator.should_use_web_search", return_value=False):
        response, _, _ = await _process_hybrid_mode(
            _request("openai is broken"),
            [],
            AIClients(openai=openai_client, perplexity=perplexity_client),
            AIConfig(),
        )

    assert response == "Perplexity fallback"
    perplexity_client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_accessor_reports_per_provider_state():
    openai_breaker = get_circuit_breaker("openai")

    async def failing_call():
        msg = "nope"
        raise ValueError(msg)

    with pytest.raises(ValueError):
        await openai_breaker.call(failing_call)

    states = get_circuit_breaker_states()

    assert states["openai"]["provider"] == "openai"
    assert states["openai"]["state"] == "CLOSED"
    assert states["openai"]["consecutive_failures"] == 1
    assert states["openai"]["last_failure_time"] > 0
    assert states["perplexity"]["provider"] == "perplexity"
    assert states["perplexity"]["state"] == "CLOSED"
    assert states["perplexity"]["consecutive_failures"] == 0
    assert states["perplexity"]["last_failure_time"] == 0
