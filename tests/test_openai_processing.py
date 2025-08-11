"""Unified tests for src/openai_processing.py.

Consolidates coverage and edge-case tests into a single module to avoid
fragmentation and improve maintainability.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.openai_processing import process_openai_message


class TestProcessOpenAIMessageBasic:
    @pytest.mark.asyncio
    async def test_success(self):
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test response from OpenAI"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.id = "test-response-id"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 70

        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = mock_response

        with patch("asyncio.to_thread") as mock_to_thread:
            mock_to_thread.return_value = mock_response

            result = await process_openai_message(
                message="Hello OpenAI",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logging.getLogger("test"),
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="You are a helpful assistant",
                output_tokens=1000,
            )

            assert result == "Test response from OpenAI"
            conversation_manager.add_message.assert_any_call(12345, "user", "Hello OpenAI")
            conversation_manager.add_message.assert_any_call(
                12345,
                "assistant",
                "Test response from OpenAI",
                metadata={"ai_service": "openai", "model": "gpt-4"},
            )

    @pytest.mark.asyncio
    async def test_no_unsupported_params(self):
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        mock_response.id = "test-id"

        openai_client = MagicMock()
        logger = logging.getLogger("test")

        with patch("src.openai_processing.logging.Logger.warning"):
            with patch("asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = mock_response

                result = await process_openai_message(
                    message="Test",
                    user=user,
                    conversation_summary=[],
                    conversation_manager=conversation_manager,
                    logger=logger,
                    openai_client=openai_client,
                    gpt_model="gpt-5",
                    system_message="Test",
                    output_tokens=1000,
                )
                assert result == "Response"

    @pytest.mark.asyncio
    async def test_empty_response(self):
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        openai_client = MagicMock()
        logger = logging.getLogger("test")

        with patch("asyncio.to_thread") as mock_to_thread:
            mock_to_thread.return_value = mock_response
            result = await process_openai_message(
                message="Test",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="Test",
                output_tokens=1000,
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_no_choices(self):
        from src.caching import conversation_cache, response_cache

        conversation_cache.clear()
        response_cache.cache.clear()

        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = []
        openai_client = MagicMock()
        logger = MagicMock()

        with patch("asyncio.to_thread") as mock_to_thread:
            mock_to_thread.return_value = mock_response
            result = await process_openai_message(
                message="Test",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="Test",
                output_tokens=1000,
            )
            assert result is None
            logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_timeout(self):
        from src.caching import conversation_cache, response_cache

        conversation_cache.clear()
        response_cache.cache.clear()

        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = MagicMock()
        logger = MagicMock()

        with patch("asyncio.to_thread", side_effect=TimeoutError("Timeout")):
            result = await process_openai_message(
                message="Test",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="Test",
                output_tokens=1000,
            )
            assert result is None
            logger.exception.assert_called()

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        from src.caching import conversation_cache, response_cache

        conversation_cache.clear()
        response_cache.cache.clear()

        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = MagicMock()
        logger = MagicMock()

        with patch("asyncio.to_thread", side_effect=Exception("Generic error")):
            result = await process_openai_message(
                message="Test",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="Test",
                output_tokens=1000,
            )
            assert result is None
            logger.exception.assert_called()
            conversation_manager.add_message.assert_not_called()


class TestProcessOpenAIMessageAdditionalCoverage:
    @pytest.mark.asyncio
    async def test_internal_api_call_logic(self):
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test response"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.id = "test-response-id"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 25
        mock_response.usage.total_tokens = 75

        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = mock_response
        logger = MagicMock()

        with (
            patch("src.openai_processing.retry_with_backoff") as mock_retry,
            patch("asyncio.to_thread") as mock_to_thread,
        ):

            async def call_function_directly(func, retry_config, logger_arg):
                return await func()

            mock_retry.side_effect = call_function_directly
            mock_to_thread.return_value = mock_response

            result = await process_openai_message(
                message="Test message for internal logic",
                user=user,
                conversation_summary=[{"role": "user", "content": "Previous message"}],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="System message",
                output_tokens=1000,
            )
            assert result == "Test response"
            assert logger.debug.call_count >= 3

    @pytest.mark.asyncio
    async def test_retry_failure(self):
        from src.caching import conversation_cache, response_cache

        conversation_cache.clear()
        response_cache.cache.clear()

        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = MagicMock()
        logger = MagicMock()

        with patch("src.openai_processing.retry_with_backoff") as mock_retry:
            mock_retry.side_effect = Exception("API call failed after retries")
            result = await process_openai_message(
                message="Test message",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="System message",
                output_tokens=1000,
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_usage_logging(self):
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response with detailed usage"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.id = "usage-test-id"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 150
        mock_response.usage.completion_tokens = 75
        mock_response.usage.total_tokens = 225

        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = mock_response
        logger = MagicMock()

        with (
            patch("src.openai_processing.retry_with_backoff") as mock_retry,
            patch("asyncio.to_thread") as mock_to_thread,
        ):

            async def call_function_directly(func, retry_config, logger_arg):
                return await func()

            mock_retry.side_effect = call_function_directly
            mock_to_thread.return_value = mock_response

            result = await process_openai_message(
                message="Test message with usage tracking",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="System message",
                output_tokens=1000,
            )
            assert result == "Response with detailed usage"

    @pytest.mark.asyncio
    async def test_whitespace_only_response(self):
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "   \n\t   "
        mock_response.choices[0].finish_reason = "stop"
        mock_response.id = "whitespace-id"
        mock_response.usage = MagicMock()

        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = mock_response
        logger = MagicMock()

        with (
            patch("src.openai_processing.retry_with_backoff") as mock_retry,
            patch("asyncio.to_thread") as mock_to_thread,
        ):

            async def call_function_directly(func, retry_config, logger_arg):
                return await func()

            mock_retry.side_effect = call_function_directly
            mock_to_thread.return_value = mock_response

            result = await process_openai_message(
                message="Test message",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="System message",
                output_tokens=1000,
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_response_logging_message_counts(self):
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "A" * 300
        mock_response.choices[0].finish_reason = "stop"
        mock_response.id = "logging-test-id"
        mock_response.usage = MagicMock()

        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = mock_response
        logger = MagicMock()

        with (
            patch("src.openai_processing.retry_with_backoff") as mock_retry,
            patch("asyncio.to_thread") as mock_to_thread,
        ):

            async def call_function_directly(func, retry_config, logger_arg):
                return await func()

            mock_retry.side_effect = call_function_directly
            mock_to_thread.return_value = mock_response

            result = await process_openai_message(
                message="Test message for logging",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="System message",
                output_tokens=1000,
            )
            assert result == "A" * 300
            assert conversation_manager.add_message.call_count == 2

    @pytest.mark.asyncio
    async def test_invalid_response_structure(self):
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = None
        mock_response.id = "invalid-structure-id"
        openai_client = MagicMock()
        openai_client.chat.completions.create.return_value = mock_response
        logger = MagicMock()

        with (
            patch("src.openai_processing.retry_with_backoff") as mock_retry,
            patch("asyncio.to_thread") as mock_to_thread,
        ):

            async def call_function_directly(func, retry_config, logger_arg):
                return await func()

            mock_retry.side_effect = call_function_directly
            mock_to_thread.return_value = mock_response

            result = await process_openai_message(
                message="Test message",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="System message",
                output_tokens=1000,
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_timeout_via_retry(self):
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = MagicMock()
        logger = MagicMock()

        with patch("src.openai_processing.retry_with_backoff") as mock_retry:
            mock_retry.side_effect = TimeoutError("API call timed out")
            result = await process_openai_message(
                message="Test message",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="System message",
                output_tokens=1000,
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_generic_exception_via_retry(self):
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        openai_client = MagicMock()
        logger = MagicMock()

        with patch("src.openai_processing.retry_with_backoff") as mock_retry:
            mock_retry.side_effect = ValueError("Generic API error")
            result = await process_openai_message(
                message="Test message",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-4",
                system_message="System message",
                output_tokens=1000,
            )
            assert result is None
