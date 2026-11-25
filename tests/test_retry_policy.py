"""Regression tests for retry policy decisions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import httpx2
import openai
import pytest

from src.error_handling import (
    DEFAULT_API_RETRY_CONFIG,
    ErrorType,
    RetryConfig,
    classify_error,
    retry_after_seconds,
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


@pytest.mark.asyncio
async def test_host_port_number_is_not_read_as_an_http_status():
    """Port 443 in a connect message is not a 443 status code."""
    error = openai.APIConnectionError(
        message="Cannot connect to host discord.com:443 ssl:default",
        request=SimpleNamespace(),
    )

    attempts, delays = await _run_raising(error)

    assert attempts == 2
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_port_in_a_plain_connection_error_is_not_an_http_status():
    """A port mentioned in prose does not turn a connection error into a 443 status."""
    error = ConnectionRefusedError("connect to host port 443")

    details = classify_error(error)
    attempts, delays = await _run_raising(error)

    assert details.error_type == ErrorType.NETWORK_ERROR
    assert attempts == 2
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_bare_number_in_prose_is_not_a_rate_limit():
    """A row count named 429 is not evidence of an HTTP rate limit."""
    error = RuntimeError("processed 429 rows")

    details = classify_error(error)
    attempts, delays = await _run_raising(error)

    assert details.error_type != ErrorType.API_RATE_LIMIT
    assert attempts == 1
    assert delays == []


@pytest.mark.parametrize("message", ["HTTP 429", "status 429"])
@pytest.mark.asyncio
async def test_explicit_status_in_text_is_still_a_rate_limit(message):
    """Text that names an HTTP status explicitly keeps its retry policy."""
    error = RuntimeError(message)

    details = classify_error(error)
    attempts, delays = await _run_raising(error)

    assert details.error_type == ErrorType.API_RATE_LIMIT
    assert attempts == 2
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_structured_429_retry_after_is_capped_at_thirty_seconds():
    """A structured status keeps the Retry-After cap even when the header is larger."""
    config = RetryConfig(
        max_attempts=2,
        base_delay=2.0,
        max_delay=10.0,
        exponential_base=2.0,
        jitter=False,
    )
    error = _api_error(openai.RateLimitError, 429, {"Retry-After": "120"})

    attempts, delays = await _run_raising(error, config)

    assert attempts == 2
    assert delays == [30.0]


@pytest.mark.asyncio
async def test_insufficient_quota_is_not_retried():
    """A quota error keeps its auth classification and is not retried."""
    error = openai.RateLimitError(
        "quota exceeded",
        response=_api_response(429),
        body={"error": {"code": "insufficient_quota", "message": "quota exhausted"}},
    )

    details = classify_error(error)
    attempts, delays = await _run_raising(error)

    assert details.error_type == ErrorType.API_AUTH_ERROR
    assert "quota exhausted" in details.user_message.lower()
    assert attempts == 1
    assert delays == []


def _real_rate_limit_error(retry_after: str) -> openai.RateLimitError:
    """Build a real SDK rate-limit error around a real HTTP response."""
    request = httpx.Request("POST", "https://api.perplexity.ai/v1/responses")
    response = httpx.Response(429, request=request, headers={"Retry-After": retry_after})
    return openai.RateLimitError("rate limited", response=response, body=None)


@pytest.mark.parametrize("header", ["nan", "inf", "-5", "", "abc", "1e999"])
@pytest.mark.asyncio
async def test_unusable_retry_after_falls_back_to_normal_backoff(header):
    """nan, inf, negative, empty, and absurd headers must not hang the retry."""
    config = RetryConfig(
        max_attempts=2,
        base_delay=2.0,
        max_delay=10.0,
        exponential_base=2.0,
        jitter=False,
    )
    error = _real_rate_limit_error(header)

    assert retry_after_seconds({"Retry-After": header}) is None
    attempts, delays = await _run_raising(error, config)

    assert attempts == 2
    assert delays == [2.0]


@pytest.mark.asyncio
async def test_usable_retry_after_still_sets_the_delay():
    """A finite positive header keeps the documented retry delay."""
    config = RetryConfig(
        max_attempts=2,
        base_delay=2.0,
        max_delay=10.0,
        exponential_base=2.0,
        jitter=False,
    )
    error = _real_rate_limit_error("30")

    attempts, delays = await _run_raising(error, config)

    assert attempts == 2
    assert delays == [30.0]


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError("connection refused"),
        __import__("socket").gaierror(-2, "Name or service not known"),
    ],
)
@pytest.mark.asyncio
async def test_connection_failures_before_a_request_are_retried(error):
    """A refused or unresolvable connection never established the request."""
    from src.error_handling import ErrorType

    details = classify_error(error)
    attempts, delays = await _run_raising(error)

    assert details.error_type == ErrorType.NETWORK_ERROR
    assert attempts == 2
    assert len(delays) == 1


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError("connection reset by peer"),
        BrokenPipeError("broken pipe"),
        ConnectionAbortedError("connection aborted"),
    ],
)
@pytest.mark.asyncio
async def test_connection_failures_after_send_are_not_retried(error):
    """Reset, broken pipe, and aborted errors may arrive after the request."""
    attempts, delays = await _run_raising(error)

    assert attempts == 1
    assert delays == []
