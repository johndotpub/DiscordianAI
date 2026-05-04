"""Tests for the API call context manager module."""

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.api_context import APICallResult, api_call, call_with_retry
from src.error_handling import error_tracker

_TEST_RUNTIME_ERROR = RuntimeError("boom")
_TEST_TIMEOUT_ERROR = ValueError("timeout simulation")
_TEST_API_ERROR = RuntimeError("API error")
_TEST_SERVER_ERROR = RuntimeError("500 server error")


@pytest.fixture
def logger():
    """Return a real logger so log messages are exercise-tested."""
    return logging.getLogger("test_api_context")


@pytest.fixture(autouse=True)
def _reset_error_tracker():
    """Clear global error tracker before each test."""
    error_tracker.error_counts.clear()
    error_tracker.error_history.clear()


@pytest.mark.asyncio
async def test_api_call_success(logger):
    """Successful call sets result and logs completion."""
    async with api_call("openai", logger) as ctx:
        ctx.set_result({"choices": [{"message": {"content": "hello"}}]})

    assert ctx.result is not None


@pytest.mark.asyncio
async def test_api_call_no_result_set(logger):
    """Warns when context exits without set_result being called."""
    with patch.object(logger, "warning") as mock_warn:
        async with api_call("openai", logger):
            pass

        mock_warn.assert_called_once()
        assert "no result was set" in mock_warn.call_args[0][0]


@pytest.mark.asyncio
async def test_api_call_exception_tracked(logger):
    """Exception inside context is classified, tracked, and re-raised."""
    with pytest.raises(RuntimeError, match="boom"):
        async with api_call("openai", logger):
            raise _TEST_RUNTIME_ERROR

    assert len(error_tracker.error_history) == 1
    record = error_tracker.error_history[0]
    assert "service" in record["context"]
    assert record["context"]["service"] == "openai"


@pytest.mark.asyncio
async def test_api_call_timing(logger):
    """Elapsed time is recorded in error tracker context."""
    with pytest.raises(ValueError):
        async with api_call("perplexity", logger):
            await asyncio.sleep(0.05)
            raise _TEST_TIMEOUT_ERROR

    record = error_tracker.error_history[-1]
    assert "elapsed_seconds" in record["context"]
    assert record["context"]["elapsed_seconds"] >= 0.04


@pytest.mark.asyncio
async def test_api_call_with_request(logger):
    """Passing an AIRequest includes user ID in log output."""
    request = MagicMock()
    request.user.id = 42

    with patch.object(logger, "info") as mock_info:
        async with api_call("openai", logger, request=request) as ctx:
            ctx.set_result("ok")

        all_calls = mock_info.call_args_list
        user_info = " for user 42"
        found = any(user_info in str(c) for c in all_calls)
        assert found, f"user info not found in log calls: {all_calls}"


@pytest.mark.asyncio
async def test_call_with_retry_success(logger):
    """call_with_retry returns APICallResult on success."""

    async def factory():
        return {"data": "response"}

    result = await call_with_retry(factory, "openai", logger)
    assert isinstance(result, APICallResult)
    assert result.success is True
    assert result.value == {"data": "response"}
    assert result.error is None
    assert result.elapsed_seconds > 0


@pytest.mark.asyncio
async def test_call_with_retry_failure(logger):
    """call_with_retry returns APICallResult on failure."""

    async def factory():
        raise _TEST_API_ERROR

    result = await call_with_retry(factory, "openai", logger, max_attempts=1)
    assert result.success is False
    assert result.error is not None
    assert "API error" in str(result.error)


@pytest.mark.asyncio
async def test_call_with_retry_with_request(logger):
    """call_with_retry passes request context."""
    request = MagicMock()
    request.user.id = 99

    async def factory():
        return "ok"

    result = await call_with_retry(factory, "perplexity", logger, request=request)
    assert result.success is True


@pytest.mark.asyncio
async def test_api_call_error_severity_mapping(logger):
    """Different error types map to correct severity levels."""
    with pytest.raises(RuntimeError):
        async with api_call("openai", logger):
            raise _TEST_SERVER_ERROR

    assert len(error_tracker.error_history) == 1
