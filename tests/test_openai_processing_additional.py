"""Additional comprehensive tests for openai_processing.py - focusing on missing coverage."""

from unittest.mock import MagicMock, patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.openai_processing import process_openai_message


class TestOpenAIProcessingAdditionalCoverage:
    """Additional tests to improve coverage for openai_processing.py."""

    @pytest.mark.asyncio
    async def test_process_openai_message_api_call_internal_logic(self):
        """Test internal API call logic and parameter building to cover lines 66-116."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        # Mock response
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

        # Create a logger to capture debug messages
        logger = MagicMock()

        # Mock retry_with_backoff to directly execute the function and test internal logic
        with (
            patch("src.openai_processing.retry_with_backoff") as mock_retry,
            patch("asyncio.to_thread") as mock_to_thread,
        ):

            # Make retry_with_backoff call the function directly
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

            # Verify debug logging was called for internal logic
            assert logger.debug.call_count >= 3

    @pytest.mark.asyncio
    async def test_process_openai_message_gpt5_minimal_parameters(self):
        """Test GPT-5 with minimal reasoning effort to cover more branches."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "GPT-5 minimal response"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.id = "gpt5-minimal-id"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

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
                gpt_model="gpt-5",
                system_message="System message",
                output_tokens=1000,
                reasoning_effort="minimal",
                verbosity="low",
            )

            assert result == "GPT-5 minimal response"

    @pytest.mark.asyncio
    async def test_process_openai_message_gpt5_invalid_parameters(self):
        """Test GPT-5 with invalid parameter values to cover warning branches."""
        # Clear caches to ensure test isolation
        from src.caching import conversation_cache, response_cache

        conversation_cache.clear()
        response_cache.cache.clear()

        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "GPT-5 response despite invalid params"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.id = "gpt5-invalid-id"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 80
        mock_response.usage.completion_tokens = 40
        mock_response.usage.total_tokens = 120

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
                gpt_model="gpt-5",
                system_message="System message",
                output_tokens=1000,
                reasoning_effort="invalid_effort",
                verbosity="invalid_verbosity",
            )

            assert result == "GPT-5 response despite invalid params"

    @pytest.mark.asyncio
    async def test_process_openai_message_non_gpt5_with_params(self):
        """Test non-GPT-5 models with GPT-5 parameters (should log info messages)."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "GPT-4 response ignoring GPT-5 params"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.id = "gpt4-ignore-id"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 60
        mock_response.usage.completion_tokens = 30
        mock_response.usage.total_tokens = 90

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
                reasoning_effort="high",
                verbosity="medium",
            )

            assert result == "GPT-4 response ignoring GPT-5 params"

    @pytest.mark.asyncio
    async def test_process_openai_message_retry_failure(self):
        """Test retry logic failure to cover lines 149-151."""
        # Clear caches to ensure test isolation
        from src.caching import conversation_cache, response_cache

        conversation_cache.clear()
        response_cache.cache.clear()

        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        openai_client = MagicMock()
        logger = MagicMock()

        # Mock retry_with_backoff to raise an exception (simulating retry exhaustion)
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
    async def test_process_openai_message_usage_logging(self):
        """Test usage information logging to cover lines 155-161."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        # Mock response with detailed usage info
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
    async def test_process_openai_message_whitespace_only_response(self):
        """Test handling of whitespace-only response content to cover lines 167-169."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        # Mock response with whitespace-only content
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "   \n\t   "  # Only whitespace
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
    async def test_process_openai_message_response_logging(self):
        """Test response logging and conversation management to cover lines 171-187."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "A" * 300  # Long response for preview testing
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

            # Verify conversation manager was called twice (user + assistant)
            assert conversation_manager.add_message.call_count == 2

    @pytest.mark.asyncio
    async def test_process_openai_message_invalid_response_structure(self):
        """Test invalid response structure to cover lines 189-191."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        # Mock response with no choices or invalid structure
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
    async def test_process_openai_message_timeout_error(self):
        """Test timeout error handling to cover lines 193-195."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        openai_client = MagicMock()
        logger = MagicMock()

        # Mock the main process to raise asyncio.TimeoutError
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
    async def test_process_openai_message_generic_exception(self):
        """Test generic exception handling to cover lines 197-202."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        openai_client = MagicMock()
        logger = MagicMock()

        # Mock to raise a generic exception
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
