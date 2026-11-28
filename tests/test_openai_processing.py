"""Tests for OpenAI message processing functionality."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.models import OpenAIConfig
from src.openai_processing import process_openai_message
from tests.helpers import assert_no_provider_body_in_logs, provider_status_error


def _config(model="gpt-5", system_message="Test"):
    return OpenAIConfig(model=model, system_message=system_message, output_tokens=1000)


def _client_returning(response):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


class TestProcessOpenAIMessageBasic:
    @pytest.mark.asyncio
    async def test_success(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = _client_returning(openai_response("Test response from OpenAI"))

        result = await process_openai_message(
            request=make_request(
                "Hello OpenAI",
                conversation_manager=conversation_manager,
            ),
            conversation_summary=[],
            openai_client=openai_client,
            config=_config(model="gpt-5-mini", system_message="You are a helpful assistant"),
        )

        assert result == "Test response from OpenAI"
        conversation_manager.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_basic_gpt5_processing(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = _client_returning(openai_response("Response"))

        result = await process_openai_message(
            request=make_request("Test", conversation_manager=conversation_manager),
            conversation_summary=[],
            openai_client=openai_client,
            config=_config(),
        )

        assert result == "Response"

    @pytest.mark.asyncio
    async def test_length_finish_reason_marks_partial_answer(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = _client_returning(
            openai_response("A partial answer", finish_reason="length")
        )

        result = await process_openai_message(
            request=make_request("Test", conversation_manager=conversation_manager),
            conversation_summary=[],
            openai_client=openai_client,
            config=_config(),
        )

        assert result == "A partial answer"
        assert getattr(result, "truncated", False) is True

    @pytest.mark.asyncio
    async def test_empty_response(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        response = openai_response()
        response.choices = []
        openai_client = _client_returning(response)
        logger = MagicMock()

        result = await process_openai_message(
            request=make_request(
                "Test",
                conversation_manager=conversation_manager,
                logger=logger,
            ),
            conversation_summary=[],
            openai_client=openai_client,
            config=_config(),
        )

        assert result is None
        logger.error.assert_called()
        conversation_manager.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_error(self, make_request):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = MagicMock()
        openai_client.chat.completions.create = AsyncMock(side_effect=TimeoutError("Timeout"))
        logger = MagicMock()

        with patch("src.error_handling.asyncio.sleep") as sleep:
            result = await process_openai_message(
                request=make_request(
                    "Test",
                    conversation_manager=conversation_manager,
                    logger=logger,
                ),
                conversation_summary=[],
                openai_client=openai_client,
                config=_config(),
            )

        assert result is None
        openai_client.chat.completions.create.assert_awaited_once()
        sleep.assert_not_awaited()
        logger.error.assert_called()
        conversation_manager.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_logs_do_not_include_provider_body(self, make_request, caplog):
        """A provider failure is logged by class, status, and type, never by body."""
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = MagicMock()
        openai_client.chat.completions.create = AsyncMock(side_effect=provider_status_error())
        logger = logging.getLogger("test_openai_provider_body")

        with patch("src.error_handling.asyncio.sleep"):
            with caplog.at_level(logging.DEBUG):
                result = await process_openai_message(
                    request=make_request(
                        "Test",
                        conversation_manager=conversation_manager,
                        logger=logger,
                    ),
                    conversation_summary=[],
                    openai_client=openai_client,
                    config=_config(),
                )

        assert result is None
        assert_no_provider_body_in_logs(caplog)
        assert any("InternalServerError" in record.getMessage() for record in caplog.records)
        conversation_manager.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_generic_error(self, make_request):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = MagicMock()
        openai_client.chat.completions.create = AsyncMock(side_effect=Exception("Generic error"))
        logger = MagicMock()

        with patch("src.error_handling.asyncio.sleep") as sleep:
            result = await process_openai_message(
                request=make_request(
                    "Test",
                    conversation_manager=conversation_manager,
                    logger=logger,
                ),
                conversation_summary=[],
                openai_client=openai_client,
                config=_config(),
            )

        assert result is None
        assert openai_client.chat.completions.create.await_count == 1
        sleep.assert_not_awaited()
        logger.error.assert_called()
        conversation_manager.add_message.assert_not_called()


class TestProcessOpenAIMessageAdditionalCoverage:
    @pytest.mark.asyncio
    async def test_internal_api_call_logic(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = _client_returning(openai_response("Test response"))
        logger = MagicMock()

        result = await process_openai_message(
            request=make_request(
                "Test message for internal logic",
                conversation_manager=conversation_manager,
                logger=logger,
            ),
            conversation_summary=[{"role": "user", "content": "Previous message"}],
            openai_client=openai_client,
            config=_config(system_message="System message"),
        )

        assert result == "Test response"
        assert logger.debug.call_count == 1

    @pytest.mark.asyncio
    async def test_usage_logging(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = _client_returning(openai_response("Response with detailed usage"))
        logger = MagicMock()

        result = await process_openai_message(
            request=make_request(
                "Test message with usage tracking",
                conversation_manager=conversation_manager,
                logger=logger,
            ),
            conversation_summary=[],
            openai_client=openai_client,
            config=_config(system_message="System message"),
        )

        assert result == "Response with detailed usage"

    @pytest.mark.asyncio
    async def test_whitespace_only_response(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = _client_returning(openai_response("   \n\t   "))
        logger = MagicMock()

        result = await process_openai_message(
            request=make_request(
                "Test message",
                conversation_manager=conversation_manager,
                logger=logger,
            ),
            conversation_summary=[],
            openai_client=openai_client,
            config=_config(system_message="System message"),
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_response_logging_message_counts(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = _client_returning(openai_response("A" * 300))
        logger = MagicMock()

        result = await process_openai_message(
            request=make_request(
                "Test message for logging",
                conversation_manager=conversation_manager,
                logger=logger,
            ),
            conversation_summary=[],
            openai_client=openai_client,
            config=_config(system_message="System message"),
        )

        assert result == "A" * 300
        conversation_manager.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_response_structure(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        response = openai_response()
        response.choices = None
        openai_client = _client_returning(response)
        logger = MagicMock()

        result = await process_openai_message(
            request=make_request(
                "Test message",
                conversation_manager=conversation_manager,
                logger=logger,
            ),
            conversation_summary=[],
            openai_client=openai_client,
            config=_config(system_message="System message"),
        )

        assert result is None
