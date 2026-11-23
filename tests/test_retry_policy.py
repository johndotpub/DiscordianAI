"""Regression tests for retry policy decisions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import httpx2
import openai
import pytest

from src.error_handling import (
    DEFAULT_API_RETRY_CONFIG,
    RetryConfig,
    retry_with_backoff,
)


def _api_response(status_code: int, headers: dict[str, str] | None = None):
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        request=SimpleNamespace(),
    )


def _api_error(
    exception_type: type[Exception],
    status_code: int,
    headers: dict[str, str] | None = None,
) -> Exception:
    return exception_type(
        "request failed", response=_api_response(status_code, headers), body=None
    )


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        "request failed",
        request=request,
        response=response,
    )


async def _run_raising(
    error: Exception,
    config: RetryConfig = DEFAULT_API_RETRY_CONFIG,
) -> tuple[int, list[float]]:
    attempts = 0

    async def failing_call():
        nonlocal attempts
        attempts += 1
        raise error

    sleep = AsyncMock()
    with patch("src.error_handling.asyncio.sleep", sleep):
        with pytest.raises(type(error)):
            await retry_with_backoff(failing_call, config, Mock())

    return attempts, [call.args[0] for call in sleep.call_args_list]


@pytest.mark.asyncio
async def test_401_is_not_retried():
    attempts, delays = await _run_raising(_http_status_error(401))

    assert attempts == 1
    assert delays == []


@pytest.mark.asyncio
async def test_400_is_not_retried():
    attempts, delays = await _run_raising(_api_error(openai.BadRequestError, 400))

    assert attempts == 1
    assert delays == []


@pytest.mark.asyncio
async def test_429_honours_retry_after():
    config = RetryConfig(
        max_attempts=2,
        base_delay=0.1,
        max_delay=1.0,
        exponential_base=2.0,
        jitter=False,
    )
    error = _api_error(openai.RateLimitError, 429, {"Retry-After": "3"})

    attempts, delays = await _run_raising(error, config)

    assert attempts == 2
    assert len(delays) == 1
    assert 3 <= delays[0] <= 30


@pytest.mark.asyncio
async def test_500_is_retried():
    attempts, delays = await _run_raising(_api_error(openai.InternalServerError, 500))

    assert attempts == 2
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_connection_error_is_retried():
    attempts, delays = await _run_raising(httpx.ConnectError("connection refused"))

    assert attempts == 2
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_read_timeout_is_not_retried():
    attempts, delays = await _run_raising(openai.APITimeoutError(request=SimpleNamespace()))

    assert attempts == 1
    assert delays == []


@pytest.mark.asyncio
async def test_deadline_stops_retries():
    clock = [0.0]
    attempts = 0

    async def slow_failure():
        nonlocal attempts
        attempts += 1
        clock[0] += 100.0
        msg = "connection refused"
        raise httpx.ConnectError(msg)

    sleep = AsyncMock()
    with (
        patch("src.error_handling.time.monotonic", side_effect=lambda: clock[0]),
        patch("src.error_handling.asyncio.sleep", sleep),
    ):
        with pytest.raises(httpx.ConnectError):
            await retry_with_backoff(slow_failure, DEFAULT_API_RETRY_CONFIG, Mock())

    assert attempts == 1
    assert not sleep.called


async def _run_raising_from(
    error: Exception,
    cause: BaseException,
    config: RetryConfig = DEFAULT_API_RETRY_CONFIG,
) -> tuple[int, list[float]]:
    attempts = 0

    async def failing_call():
        nonlocal attempts
        attempts += 1
        raise error from cause

    sleep = AsyncMock()
    with patch("src.error_handling.asyncio.sleep", sleep):
        with pytest.raises(type(error)):
            await retry_with_backoff(failing_call, config, Mock())

    return attempts, [call.args[0] for call in sleep.call_args_list]


@pytest.mark.asyncio
async def test_wrapped_connect_timeout_is_retried():
    """A connect timeout sent nothing, so it is safe to try again."""
    cause = httpx2.ConnectTimeout("connect timed out")
    error = openai.APITimeoutError(request=SimpleNamespace())

    attempts, delays = await _run_raising_from(error, cause)

    assert attempts == 2
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_wrapped_read_timeout_is_not_retried():
    """A read timeout may have been served, so it is not retried."""
    cause = httpx2.ReadTimeout("read timed out")
    error = openai.APITimeoutError(request=SimpleNamespace())

    attempts, delays = await _run_raising_from(error, cause)

    assert attempts == 1
    assert delays == []


@pytest.mark.asyncio
async def test_wrapped_connect_error_is_retried():
    """A connect error never established the request."""
    cause = httpx2.ConnectError("connection refused")
    error = openai.APIConnectionError(message="connection failed", request=SimpleNamespace())

    attempts, delays = await _run_raising_from(error, cause)

    assert attempts == 2
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_wrapped_read_error_is_not_retried():
    """A read error can arrive after the provider already served the request."""
    cause = httpx2.ReadError("connection dropped")
    error = openai.APIConnectionError(message="connection failed", request=SimpleNamespace())

    attempts, delays = await _run_raising_from(error, cause)

    assert attempts == 1
    assert delays == []


@pytest.mark.asyncio
async def test_wrapped_remote_protocol_error_is_not_retried():
    """A protocol error after send is not proof the request can be replayed."""
    cause = httpx2.RemoteProtocolError("peer closed connection")
    error = openai.APIConnectionError(message="connection failed", request=SimpleNamespace())

    attempts, delays = await _run_raising_from(error, cause)

    assert attempts == 1
    assert delays == []
