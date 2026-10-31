"""Regression tests for typed error classification and OpenAI failure visibility."""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import openai
import pytest

from src.caching import request_deduplicator, response_cache
from src.error_handling import ErrorType, classify_error, error_tracker
from src.models import AIRequest, OpenAIConfig
from src.openai_processing import process_openai_message


def _mock_response(status_code: int, headers: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        request=SimpleNamespace(),
    )


def _make_request(logger: logging.Logger) -> AIRequest:
    user = MagicMock()
    user.id = 12345
    return AIRequest(
        message=f"classification test {uuid.uuid4()}",
        user=user,
        conversation_manager=MagicMock(),
        logger=logger,
    )


def _client_returning(content: str) -> MagicMock:
    client = MagicMock()

    async def create(**_kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason="stop",
                )
            ]
        )

    client.chat.completions.create = create
    return client


def _client_raising(exception: Exception) -> MagicMock:
    client = MagicMock()

    async def create(**_kwargs):
        raise exception

    client.chat.completions.create = create
    return client


@pytest.fixture(autouse=True)
def _reset_process_state():
    response_cache.cache.clear()
    request_deduplicator._pending_requests.clear()
    error_tracker.error_counts.clear()
    error_tracker.error_history.clear()


@pytest.mark.asyncio
async def test_successful_openai_call_does_not_warn_about_missing_result(caplog):
    caplog.set_level(logging.WARNING)
    request = _make_request(logging.getLogger("test_openai_success"))

    result = await process_openai_message(
        request=request,
        conversation_summary=[],
        openai_client=_client_returning("A successful answer"),
        config=OpenAIConfig(),
    )

    assert result == "A successful answer"
    assert not any("no result was set" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_failed_openai_call_logs_failure_and_tracks_server_error(caplog):
    caplog.set_level(logging.WARNING)
    request = _make_request(logging.getLogger("test_openai_server_error"))
    server_error = openai.InternalServerError(
        "The server had an error",
        response=_mock_response(500),
        body=None,
    )

    with patch("src.error_handling.asyncio.sleep", new=AsyncMock()):
        result = await process_openai_message(
            request=request,
            conversation_summary=[],
            openai_client=_client_raising(server_error),
            config=OpenAIConfig(),
        )

    assert result is None
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "api_call: openai failed" in message and "severity=high" in message for message in messages
    )
    assert error_tracker.error_counts.get("api_server_error_high") == 1


def test_classify_real_openai_exceptions_by_type():
    internal_error = openai.InternalServerError(
        "The server had an error",
        response=_mock_response(500),
        body=None,
    )
    rate_limit = openai.RateLimitError(
        "Too many requests",
        response=_mock_response(429),
        body=None,
    )
    timeout = openai.APITimeoutError(request=SimpleNamespace())
    connection = openai.APIConnectionError(
        message="A transport problem occurred",
        request=SimpleNamespace(),
    )

    assert classify_error(internal_error).error_type == ErrorType.API_SERVER_ERROR
    assert classify_error(rate_limit).error_type == ErrorType.API_RATE_LIMIT
    assert classify_error(timeout).error_type == ErrorType.API_TIMEOUT
    assert classify_error(connection).error_type == ErrorType.NETWORK_ERROR


def test_rate_limit_uses_retry_after_response_header():
    rate_limit = openai.RateLimitError(
        "Too many requests",
        response=_mock_response(429, {"Retry-After": "30"}),
        body=None,
    )

    assert classify_error(rate_limit).retry_after == 30


@pytest.mark.asyncio
async def test_process_openai_message_returns_none_on_provider_failure():
    request = _make_request(logging.getLogger("test_openai_fallback"))
    server_error = openai.InternalServerError(
        "The server had an error",
        response=_mock_response(500),
        body=None,
    )

    with patch("src.error_handling.asyncio.sleep", new=AsyncMock()):
        result = await process_openai_message(
            request=request,
            conversation_summary=[],
            openai_client=_client_raising(server_error),
            config=OpenAIConfig(),
        )

    assert result is None


def test_removed_error_message_classifier_has_no_references():
    src_root = Path(__file__).resolve().parents[1] / "src"
    references = [
        path
        for path in src_root.rglob("*.py")
        if "classify_error_message" in path.read_text(encoding="utf-8")
    ]

    assert references == []
