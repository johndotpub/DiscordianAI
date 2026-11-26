"""Regression tests for provider circuit-breaker wiring.

These tests exercise the breakers as production code uses them: one breaker
per provider, wrapping the whole retry sequence for a single logical call.
"""

import asyncio
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
from src.models import AIClients, AIConfig, AIRequest, OpenAIConfig, PerplexityConfig
from src.openai_processing import process_openai_message
from src.perplexity_processing import process_perplexity_message
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


def _failing_perplexity_client() -> MagicMock:
    client = MagicMock()
    client.responses.create = AsyncMock(side_effect=_server_error())
    return client


def _perplexity_client(text: str) -> MagicMock:
    response = SimpleNamespace(
        output=[
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ]
    )
    client = MagicMock()
    client.responses.create = AsyncMock(return_value=response)
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
async def test_provider_call_counts_one_failure_after_an_internal_retry():
    breaker = get_circuit_breaker("openai")
    client = _failing_client()

    with patch("src.error_handling.asyncio.sleep", new=AsyncMock()):
        result = await process_openai_message(
            _request("one logical call with a retry"),
            [],
            client,
            OpenAIConfig(),
        )

    assert result is None
    assert client.chat.completions.create.await_count == 2
    assert breaker.failure_count == 1
    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_perplexity_call_counts_one_failure_after_an_internal_retry():
    """The Perplexity adapter wraps its retry sequence in one breaker call."""
    breaker = get_circuit_breaker("perplexity")
    client = _failing_perplexity_client()

    with patch("src.error_handling.asyncio.sleep", new=AsyncMock()):
        result = await process_perplexity_message(
            _request("one logical perplexity call with a retry"),
            client,
            PerplexityConfig(),
        )

    assert result is None
    assert client.responses.create.await_count == 2
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
    response, _, _ = await _process_hybrid_mode(
        _request("openai is broken"),
        [],
        AIClients(openai=openai_client, perplexity=perplexity_client),
        AIConfig(),
    )

    assert response == "Perplexity fallback"
    perplexity_client.responses.create.assert_awaited_once()


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


@pytest.mark.asyncio
async def test_deterministic_client_errors_do_not_open_the_breaker():
    """Five 4xx answers must leave the provider healthy and admit later calls."""
    breaker = get_circuit_breaker("openai")
    request = httpx.Request("POST", "https://api.example/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "invalid request", "type": "invalid_request_error"}},
    )
    bad_request = openai.BadRequestError(
        "invalid request",
        response=response,
        body=response.json(),
    )

    async def rejected():
        raise bad_request

    for _ in range(5):
        with pytest.raises(openai.BadRequestError):
            await breaker.call(rejected)

    assert breaker.state == "CLOSED"
    assert breaker.failure_count == 0
    assert breaker.last_success_time == 0.0

    async def healthy_call():
        return "ok"

    for _ in range(20):
        assert await breaker.call(healthy_call) == "ok"


@pytest.mark.parametrize(
    ("error_type", "status_code"),
    [
        (openai.AuthenticationError, 401),
        (openai.PermissionDeniedError, 403),
        (openai.NotFoundError, 404),
    ],
)
@pytest.mark.asyncio
async def test_configuration_errors_count_as_provider_failures(error_type, status_code):
    """A revoked key or retired model must make the provider look unhealthy."""
    breaker = CircuitBreaker(failure_threshold=5)
    request = httpx.Request("POST", "https://api.example/v1/chat/completions")
    response = httpx.Response(
        status_code,
        request=request,
        json={"error": {"message": "request rejected", "type": "invalid_request_error"}},
    )
    error = error_type("request rejected", response=response, body=response.json())

    async def rejected():
        raise error

    for expected_failures in range(1, 6):
        with pytest.raises(error_type):
            await breaker.call(rejected)
        assert breaker.failure_count == expected_failures
        assert breaker.last_success_time == 0.0

    assert breaker.state == "OPEN"


@pytest.mark.parametrize(
    ("error_field", "error_value"),
    [
        ("type", "invalid_model"),
        ("code", "model_not_found"),
    ],
)
@pytest.mark.asyncio
async def test_a_400_invalid_model_counts_as_a_provider_failure(error_field, error_value):
    """A retired or unknown model fails every call, so /health must not stay green."""
    breaker = CircuitBreaker(failure_threshold=5)
    request = httpx.Request("POST", "https://api.perplexity.ai/v1/responses")
    response = httpx.Response(
        400,
        request=request,
        json={
            "error": {
                "message": "model is not supported",
                error_field: error_value,
            }
        },
    )
    error = openai.BadRequestError(
        "model is not supported",
        response=response,
        body=response.json(),
    )

    async def rejected():
        raise error

    for expected_failures in range(1, 6):
        with pytest.raises(openai.BadRequestError):
            await breaker.call(rejected)
        assert breaker.failure_count == expected_failures
        assert breaker.last_success_time == 0.0

    assert breaker.state == "OPEN"


@pytest.mark.asyncio
async def test_a_neutral_request_error_releases_a_half_open_probe():
    """A user's bad request must not hold the single half-open probe slot."""
    breaker = CircuitBreaker(failure_threshold=1, timeout=60)
    breaker.state = "OPEN"
    breaker.failure_count = 1
    breaker.last_failure_time = time.monotonic() - 61
    request = httpx.Request("POST", "https://api.example/v1/chat/completions")
    response = httpx.Response(
        422,
        request=request,
        json={"error": {"message": "invalid request", "type": "invalid_request_error"}},
    )

    message = "invalid request"

    async def rejected():
        raise openai.UnprocessableEntityError(
            message,
            response=response,
            body=response.json(),
        )

    with pytest.raises(openai.UnprocessableEntityError):
        await breaker.call(rejected)

    async def recovered():
        return "ok"

    assert await breaker.call(recovered) == "ok"
    assert breaker.state == "CLOSED"
    assert breaker.failure_count == 0


@pytest.mark.asyncio
async def test_a_success_while_closed_resets_consecutive_failures():
    """One transient failure followed by a success leaves a clean count."""
    breaker = CircuitBreaker(failure_threshold=5)

    async def server_error():
        raise _server_error()

    with pytest.raises(openai.InternalServerError):
        await breaker.call(server_error)
    assert breaker.failure_count == 1

    async def healthy_call():
        return "ok"

    assert await breaker.call(healthy_call) == "ok"
    assert breaker.failure_count == 0
    assert breaker.state == "CLOSED"
