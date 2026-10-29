"""Regression tests for retry policy decisions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import openai
import pytest

from src.error_handling import (
    DEFAULT_API_RETRY_CONFIG,
    RetryConfig,
    retry_with_backoff,
)
from src.web_scraper import scrape_url_content

_PUBLIC_ADDR_INFO = [
    (2, 1, 6, "", ("93.184.216.34", 0)),
]


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


def _aiter_bytes(chunks: list[bytes]):
    async def _generator():
        for chunk in chunks:
            yield chunk

    return _generator()


def _stream(status_code: int, body: bytes = b""):
    request = httpx.Request("GET", "https://example.com")
    response = Mock()
    response.status_code = status_code
    response.headers = {
        "content-type": "text/html; charset=utf-8",
        "content-length": str(len(body)),
    }

    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status_code} response",
            request=request,
            response=response,
        )
    else:
        response.raise_for_status.return_value = None
        response.aiter_bytes = Mock(return_value=_aiter_bytes([body]))

    stream = Mock()
    stream.__aenter__ = AsyncMock(return_value=response)
    stream.__aexit__ = AsyncMock(return_value=False)
    return stream


def _client_with_streams(streams: list[Mock]):
    client = Mock()
    client.stream.side_effect = streams
    client_context = Mock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)
    return Mock(return_value=client_context), client


@pytest.mark.asyncio
async def test_scraper_retries_503_but_not_other_4xx():
    html = b"<html><head><title>Recovered</title></head><body><p>content</p></body></html>"
    client_class, client = _client_with_streams([_stream(503), _stream(200, html)])

    with (
        patch("src.web_scraper.httpx.AsyncClient", client_class),
        patch("src.web_scraper.asyncio.sleep", new=AsyncMock()),
        patch("src.web_scraper._resolve_hostname", new=AsyncMock(return_value=_PUBLIC_ADDR_INFO)),
    ):
        result = await scrape_url_content("https://example.com")

    assert result is not None
    assert client.stream.call_count == 2

    client_class, client = _client_with_streams([_stream(404)])

    with (
        patch("src.web_scraper.httpx.AsyncClient", client_class),
        patch("src.web_scraper.asyncio.sleep", new=AsyncMock()),
        patch("src.web_scraper._resolve_hostname", new=AsyncMock(return_value=_PUBLIC_ADDR_INFO)),
    ):
        result = await scrape_url_content("https://example.com")

    assert result is None
    assert client.stream.call_count == 1
