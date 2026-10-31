"""Tests for OpenAI message processing functionality."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.models import OpenAIConfig
from src.openai_processing import process_openai_message


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
        logger.exception.assert_called()
        conversation_manager.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_generic_error(self, make_request):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = MagicMock()
        openai_client.chat.completions.create = AsyncMock(side_effect=Exception("Generic error"))
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
        logger.exception.assert_called()
        conversation_manager.add_message.assert_not_called()


class TestProcessOpenAIMessageAdditionalCoverage:
    @pytest.mark.asyncio
    async def test_internal_api_call_logic(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = _client_returning(openai_response("Test response"))
        logger = MagicMock()

        with patch("src.openai_processing.retry_with_backoff") as mock_retry:

            async def call_function_directly(func, retry_config, logger_arg):
                return await func()

            mock_retry.side_effect = call_function_directly

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
            assert logger.debug.call_count >= 1

    @pytest.mark.asyncio
    async def test_usage_logging(self, make_request, openai_response):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = _client_returning(openai_response("Response with detailed usage"))
        logger = MagicMock()

        with patch("src.openai_processing.retry_with_backoff") as mock_retry:

            async def call_function_directly(func, retry_config, logger_arg):
                return await func()

            mock_retry.side_effect = call_function_directly

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

        with patch("src.openai_processing.retry_with_backoff") as mock_retry:

            async def call_function_directly(func, retry_config, logger_arg):
                return await func()

            mock_retry.side_effect = call_function_directly

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

        with patch("src.openai_processing.retry_with_backoff") as mock_retry:

            async def call_function_directly(func, retry_config, logger_arg):
                return await func()

            mock_retry.side_effect = call_function_directly

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

        with patch("src.openai_processing.retry_with_backoff") as mock_retry:

            async def call_function_directly(func, retry_config, logger_arg):
                return await func()

            mock_retry.side_effect = call_function_directly

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
