"""Comprehensive integration tests for API interactions using mocks.

This test suite covers:
- OpenAI API integration with realistic response simulation
- Perplexity API integration with citation handling
- Discord API integration with message sending
- Error handling for various API failure scenarios
- Rate limiting and retry logic validation
"""

import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.api_utils import APICallBuilder, log_api_call, log_api_response
from src.conversation_manager import ThreadSafeConversationManager
from src.error_handling import ErrorType, classify_error, safe_discord_send
from src.openai_processing import process_openai_message
from src.perplexity_processing import process_perplexity_message


class TestOpenAIAPIIntegration:
    """Integration tests for OpenAI API interactions."""

    @pytest.mark.asyncio
    async def test_openai_successful_response_integration(self):
        """Test complete OpenAI integration with successful response."""
        # Mock user and conversation manager
        user = Mock()
        user.id = 12345

        conversation_manager = Mock(spec=ThreadSafeConversationManager)

        # Mock OpenAI response structure
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "This is a test response from OpenAI"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.id = "chatcmpl-test123"
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 25
        mock_response.usage.completion_tokens = 15
        mock_response.usage.total_tokens = 40

        # Mock OpenAI client
        openai_client = Mock()
        openai_client.chat.completions.create.return_value = mock_response

        logger = logging.getLogger("test")

        # Test the integration
        result = await process_openai_message(
            message="Test message",
            user=user,
            conversation_summary=[],
            conversation_manager=conversation_manager,
            logger=logger,
            openai_client=openai_client,
            gpt_model="gpt-5-mini",
            system_message="You are a test assistant",
            output_tokens=1000,
        )

        # Verify results
        assert result == "This is a test response from OpenAI"

        # Verify OpenAI API was called with correct parameters
        openai_client.chat.completions.create.assert_called_once()
        call_args = openai_client.chat.completions.create.call_args[1]
        assert call_args["model"] == "gpt-5-mini"
        assert call_args["max_completion_tokens"] == 1000
        assert len(call_args["messages"]) == 2  # system + user message

        # Verify conversation history was updated
        assert conversation_manager.add_message.call_count == 2  # user + assistant

    @pytest.mark.asyncio
    async def test_openai_api_error_handling(self):
        """Test OpenAI API error handling and classification."""
        # Clear caches to ensure test isolation
        from src.caching import conversation_cache, response_cache

        conversation_cache.clear()
        response_cache.cache.clear()

        user = Mock()
        user.id = 12345

        conversation_manager = Mock(spec=ThreadSafeConversationManager)

        # Mock OpenAI client that raises an exception
        openai_client = Mock()
        openai_client.chat.completions.create.side_effect = Exception("API rate limit exceeded")

        logger = logging.getLogger("test")

        # Test error handling
        result = await process_openai_message(
            message="Test message",
            user=user,
            conversation_summary=[],
            conversation_manager=conversation_manager,
            logger=logger,
            openai_client=openai_client,
            gpt_model="gpt-5-mini",
            system_message="You are a test assistant",
            output_tokens=1000,
        )

        # Should return None on failure
        assert result is None

        # Verify conversation history was not updated on failure
        conversation_manager.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_gpt5_parameters_integration(self):
        """GPT-5-specific parameters are not supported; ensure normal behavior."""
        user = Mock()
        user.id = 12345

        conversation_manager = Mock(spec=ThreadSafeConversationManager)

        # Mock successful GPT-5 response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "GPT-5 response with reasoning"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.id = "chatcmpl-gpt5-test"
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 30
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 50

        openai_client = Mock()
        openai_client.chat.completions.create.return_value = mock_response

        logger = logging.getLogger("test")

        # Test GPT-5 model without special parameters
        result = await process_openai_message(
            message="Complex reasoning task",
            user=user,
            conversation_summary=[],
            conversation_manager=conversation_manager,
            logger=logger,
            openai_client=openai_client,
            gpt_model="gpt-5",
            system_message="You are a reasoning assistant",
            output_tokens=2000,
        )

        assert result == "GPT-5 response with reasoning"

        # Verify call did not include unsupported parameters
        call_args = openai_client.chat.completions.create.call_args[1]
        assert call_args["model"] == "gpt-5"
        assert "reasoning_effort" not in call_args
        assert "verbosity" not in call_args


class TestPerplexityAPIIntegration:
    """Integration tests for Perplexity API interactions."""

    @pytest.mark.asyncio
    async def test_perplexity_successful_response_with_citations(self):
        """Test complete Perplexity integration with citations."""
        user = Mock()
        user.id = 67890

        conversation_manager = Mock(spec=ThreadSafeConversationManager)

        # Mock Perplexity response with citations
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = (
            "Based on recent research [1], AI development continues to advance. "
            "The latest findings [2] show promising results. "
            "https://example.com/research1 https://example.com/research2"
        )
        mock_response.id = "ppl-test-123"
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 35
        mock_response.usage.completion_tokens = 45
        mock_response.usage.total_tokens = 80

        perplexity_client = Mock()
        perplexity_client.chat.completions.create.return_value = mock_response

        logger = logging.getLogger("test")

        # Test the integration
        result = await process_perplexity_message(
            message="What are the latest AI developments?",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
            perplexity_client=perplexity_client,
            system_message="You are a web search assistant",
            output_tokens=1500,
            model="sonar-pro",
        )

        # Verify results
        assert result is not None
        response_text, suppress_embeds, embed_data = result
        assert "AI development continues to advance" in response_text

        # Should have embed data since citations are present
        assert embed_data is not None
        assert "embed" in embed_data
        assert "citations" in embed_data

        # Verify API call parameters
        call_args = perplexity_client.chat.completions.create.call_args[1]
        assert call_args["model"] == "sonar-pro"
        assert call_args["max_tokens"] == 1500
        assert call_args["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_perplexity_error_handling(self):
        """Test Perplexity API error handling."""
        user = Mock()
        user.id = 67890

        conversation_manager = Mock(spec=ThreadSafeConversationManager)

        # Mock client that raises timeout error
        perplexity_client = Mock()
        perplexity_client.chat.completions.create.side_effect = TimeoutError("Request timed out")

        logger = logging.getLogger("test")

        # Test error handling
        result = await process_perplexity_message(
            message="Test query",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
            perplexity_client=perplexity_client,
        )

        # Should return None on timeout
        assert result is None

        # Conversation should not be updated on failure
        conversation_manager.add_message.assert_not_called()


class TestDiscordAPIIntegration:
    """Integration tests for Discord API interactions."""

    @pytest.mark.asyncio
    async def test_safe_discord_send_success(self):
        """Test successful Discord message sending."""
        # Mock Discord channel
        channel = AsyncMock()
        logger = logging.getLogger("test")

        # Test successful send
        result = await safe_discord_send(
            channel=channel, content="Test message", logger=logger, max_retries=3
        )

        assert result is True
        channel.send.assert_called_once_with("Test message")

    @pytest.mark.asyncio
    async def test_safe_discord_send_with_retries(self):
        """Test Discord send with retry logic."""
        # Mock channel that fails first attempt then succeeds
        channel = AsyncMock()
        channel.send.side_effect = [
            Exception("Rate limited"),  # First attempt fails
            None,  # Second attempt succeeds
        ]

        logger = logging.getLogger("test")

        with patch("asyncio.sleep") as mock_sleep:
            result = await safe_discord_send(
                channel=channel, content="Retry test message", logger=logger, max_retries=3
            )

        assert result is True
        assert channel.send.call_count == 2
        mock_sleep.assert_called_once_with(1)  # First retry delay

    @pytest.mark.asyncio
    async def test_safe_discord_send_max_retries_exceeded(self):
        """Test Discord send when max retries are exceeded."""
        # Mock channel that always fails
        channel = AsyncMock()
        channel.send.side_effect = Exception("Persistent error")

        logger = logging.getLogger("test")

        with patch("asyncio.sleep"):
            result = await safe_discord_send(
                channel=channel, content="Failed message", logger=logger, max_retries=2
            )

        assert result is False
        assert channel.send.call_count == 2


class TestAPIErrorClassification:
    """Test error classification for different API scenarios."""

    def test_classify_openai_rate_limit_error(self):
        """Test classification of OpenAI rate limit errors."""
        error = Exception("Rate limit exceeded. Please try again in 30 seconds.")
        details = classify_error(error)

        assert details.error_type == ErrorType.API_RATE_LIMIT
        assert "Service is busy" in details.user_message
        assert details.retry_after == 30

    def test_classify_api_timeout_error(self):
        """Test classification of API timeout errors."""
        error = Exception("Request timed out after 30 seconds")
        details = classify_error(error)

        assert details.error_type == ErrorType.API_TIMEOUT
        assert "timed out" in details.user_message
        assert details.retry_after == 10

    def test_classify_authentication_error(self):
        """Test classification of authentication errors."""
        error = Exception("401 Unauthorized: Invalid API key")
        details = classify_error(error)

        assert details.error_type == ErrorType.API_AUTH_ERROR
        assert "Authentication issue" in details.user_message
        assert details.retry_after is None

    def test_classify_server_error(self):
        """Test classification of server errors."""
        error = Exception("500 Internal Server Error")
        details = classify_error(error)

        assert details.error_type == ErrorType.API_SERVER_ERROR
        assert "temporarily unavailable" in details.user_message
        assert details.retry_after == 60


class TestAPIUtilities:
    """Test API utility functions."""

    def test_api_call_builder_openai(self):
        """Test OpenAI API call builder."""
        params = APICallBuilder.openai_call(
            model="gpt-5-mini",
            system_message="Test system message",
            conversation_summary=[{"role": "user", "content": "Previous message"}],
            user_message="Current user message",
            output_tokens=2000,
        )

        assert params["model"] == "gpt-5-mini"
        assert params["max_completion_tokens"] == 2000
        assert len(params["messages"]) == 3  # system + previous + current

    def test_api_call_builder_perplexity(self):
        """Test Perplexity API call builder."""
        params = APICallBuilder.perplexity_call(
            system_message="Web search assistant",
            user_message="Search query",
            model="sonar-pro",
            max_tokens=1500,
            temperature=0.8,
        )

        assert params["model"] == "sonar-pro"
        assert params["max_tokens"] == 1500
        assert params["temperature"] == 0.8
        assert len(params["messages"]) == 2  # system + user

    def test_log_api_call(self):
        """Test API call logging utility."""
        logger = Mock()

        log_api_call(
            logger=logger,
            service="OpenAI",
            model="gpt-5-mini",
            message_length=150,
            conversation_length=5,
        )

        # Verify logger was called with appropriate messages
        logger.info.assert_called_once()
        logger.debug.assert_called_once()

        # Check info call for service and model
        info_call_args = logger.info.call_args[0][0]
        assert "OpenAI" in info_call_args
        assert "gpt-5-mini" in info_call_args

        # Check debug call for message stats
        debug_call_args = logger.debug.call_args[0][0]
        assert "150 chars" in debug_call_args
        assert "5 messages" in debug_call_args

    def test_log_api_response(self):
        """Test API response logging utility."""
        logger = Mock()

        log_api_response(
            logger=logger,
            service="Perplexity",
            response_length=800,
            metadata={"citations": 3, "model": "sonar-pro"},
        )

        # Verify logger was called
        logger.info.assert_called_once()
        call_args = logger.info.call_args[0][0]
        assert "Perplexity" in call_args
        assert "800" in call_args


@pytest.mark.asyncio
class TestIntegrationScenarios:
    """Test realistic end-to-end integration scenarios."""

    async def test_hybrid_mode_integration_scenario(self):
        """Test a realistic hybrid mode scenario with fallback."""
        # This test would simulate the smart orchestrator choosing between APIs
        # and handling fallbacks appropriately

        # Mock components
        user = Mock()
        user.id = 99999

        conversation_manager = Mock(spec=ThreadSafeConversationManager)
        conversation_manager.get_conversation_summary_formatted.return_value = []

        logger = logging.getLogger("test")

        # Mock Perplexity failure and OpenAI success
        perplexity_client = Mock()
        perplexity_client.chat.completions.create.side_effect = Exception("Perplexity unavailable")

        openai_client = Mock()
        openai_response = Mock()
        openai_response.choices = [Mock()]
        openai_response.choices[0].message.content = "Fallback response from OpenAI"
        openai_response.choices[0].finish_reason = "stop"
        openai_response.usage = Mock()
        openai_response.usage.prompt_tokens = 20
        openai_response.usage.completion_tokens = 30
        openai_response.usage.total_tokens = 50
        openai_client.chat.completions.create.return_value = openai_response

        # Test that the system can handle API failures gracefully
        # This would be tested through the smart orchestrator integration
        # but for this test we verify the individual components work

        # Verify Perplexity fails gracefully
        perplexity_result = await process_perplexity_message(
            message="Test web search",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
            perplexity_client=perplexity_client,
        )
        assert perplexity_result is None

        # Verify OpenAI works as fallback
        openai_result = await process_openai_message(
            message="Test fallback",
            user=user,
            conversation_summary=[],
            conversation_manager=conversation_manager,
            logger=logger,
            openai_client=openai_client,
            gpt_model="gpt-5-mini",
            system_message="Fallback assistant",
            output_tokens=1000,
        )
        assert openai_result == "Fallback response from OpenAI"


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v"])
