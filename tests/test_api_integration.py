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

from src.conversation_manager import ThreadSafeConversationManager
from src.error_handling import ErrorType, classify_error, safe_discord_send
from src.models import OpenAIConfig, PerplexityConfig
from src.openai_processing import process_openai_message
from src.perplexity_processing import process_perplexity_message


class TestOpenAIAPIIntegration:
    """Integration tests for OpenAI API interactions."""

    @pytest.mark.asyncio
    async def test_openai_successful_response_integration(self, make_request, openai_response):
        """Test complete OpenAI integration with successful response."""
        conversation_manager = Mock(spec=ThreadSafeConversationManager)
        openai_client = Mock()
        openai_client.chat.completions.create = AsyncMock(
            return_value=openai_response("This is a test response from OpenAI")
        )

        result = await process_openai_message(
            request=make_request("Test message", conversation_manager=conversation_manager),
            conversation_summary=[],
            openai_client=openai_client,
            config=OpenAIConfig(
                model="gpt-5-mini",
                system_message="You are a test assistant",
                output_tokens=1000,
            ),
        )

        assert result == "This is a test response from OpenAI"

        openai_client.chat.completions.create.assert_called_once()
        call_args = openai_client.chat.completions.create.call_args[1]
        assert call_args["model"] == "gpt-5-mini"
        assert call_args["max_completion_tokens"] == 1000
        assert len(call_args["messages"]) == 2  # system + user message

        conversation_manager.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_openai_api_error_handling(self, make_request):
        """Test OpenAI API error handling and classification."""
        conversation_manager = Mock(spec=ThreadSafeConversationManager)
        openai_client = Mock()
        openai_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API rate limit exceeded")
        )

        result = await process_openai_message(
            request=make_request("Test message", conversation_manager=conversation_manager),
            conversation_summary=[],
            openai_client=openai_client,
            config=OpenAIConfig(
                model="gpt-5-mini",
                system_message="You are a test assistant",
                output_tokens=1000,
            ),
        )

        assert result is None

        conversation_manager.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_gpt5_parameters_integration(self, make_request, openai_response):
        """GPT-5-specific parameters are not supported; ensure normal behavior."""
        conversation_manager = Mock(spec=ThreadSafeConversationManager)
        openai_client = Mock()
        openai_client.chat.completions.create = AsyncMock(
            return_value=openai_response("GPT-5 response with reasoning")
        )

        result = await process_openai_message(
            request=make_request(
                "Complex reasoning task",
                conversation_manager=conversation_manager,
            ),
            conversation_summary=[],
            openai_client=openai_client,
            config=OpenAIConfig(
                model="gpt-5",
                system_message="You are a reasoning assistant",
                output_tokens=2000,
            ),
        )

        assert result == "GPT-5 response with reasoning"

        call_args = openai_client.chat.completions.create.call_args[1]
        assert call_args["model"] == "gpt-5"
        assert "reasoning_effort" not in call_args
        assert "verbosity" not in call_args


class TestPerplexityAPIIntegration:
    """Integration tests for Perplexity API interactions."""

    @pytest.mark.asyncio
    async def test_perplexity_successful_response_with_citations(
        self, make_request, perplexity_response
    ):
        """Test complete Perplexity integration with citations."""
        conversation_manager = Mock(spec=ThreadSafeConversationManager)
        response = perplexity_response(
            content=(
                "Based on recent research [1], AI development continues to advance. "
                "The latest findings [2] show promising results."
            ),
            citations=[
                "https://example.com/research1",
                "https://example.com/research2",
            ],
        )
        perplexity_client = Mock()
        perplexity_client.chat.completions.create = AsyncMock(return_value=response)

        request = make_request(
            "What are the latest AI developments?",
            conversation_manager=conversation_manager,
        )
        result = await process_perplexity_message(
            request,
            perplexity_client,
            PerplexityConfig(
                model="sonar-pro",
                system_message="You are a web search assistant",
                output_tokens=1500,
            ),
        )

        assert result is not None
        response_text, _suppress_embeds, embed_data = result

        expected_text = (
            "Based on recent research [1], "
            "AI development continues to advance. "
            "The latest findings [2] show promising results."
        )
        assert (
            response_text == expected_text
        ), "Expected marker-only text for history, got: " + repr(response_text)
        assert "https://example.com/research1" not in response_text
        assert "https://example.com/research2" not in response_text

        assert embed_data is not None
        assert "embed" in embed_data
        assert "citations" in embed_data
        assert embed_data["citations"]["1"] == "https://example.com/research1"
        assert embed_data["citations"]["2"] == "https://example.com/research2"

        embed = embed_data["embed"]
        assert "AI development continues to advance" in embed.description

        call_args = perplexity_client.chat.completions.create.call_args[1]
        assert call_args["model"] == "sonar-pro"
        assert call_args["max_tokens"] == 1500

    @pytest.mark.asyncio
    async def test_perplexity_error_handling(self, make_request):
        """Test Perplexity API error handling."""
        conversation_manager = Mock(spec=ThreadSafeConversationManager)
        perplexity_client = Mock()
        perplexity_client.chat.completions.create = AsyncMock(
            side_effect=TimeoutError("Request timed out")
        )

        result = await process_perplexity_message(
            make_request("Test query", conversation_manager=conversation_manager),
            perplexity_client,
            PerplexityConfig(),
        )

        assert result is None

        conversation_manager.add_message.assert_not_called()


class TestDiscordAPIIntegration:
    """Integration tests for Discord API interactions."""

    @pytest.mark.asyncio
    async def test_safe_discord_send_success(self):
        """Test successful Discord message sending."""
        channel = AsyncMock()
        logger = logging.getLogger("test")

        result = await safe_discord_send(
            channel=channel,
            content="Test message",
            logger=logger,
            max_retries=3,
        )

        assert result is True
        channel.send.assert_called_once_with("Test message")

    @pytest.mark.asyncio
    async def test_safe_discord_send_with_retries(self):
        """Test Discord send with retry logic."""
        channel = AsyncMock()
        channel.send.side_effect = [
            Exception("Rate limited"),
            None,
        ]

        logger = logging.getLogger("test")

        with patch("asyncio.sleep") as mock_sleep:
            result = await safe_discord_send(
                channel=channel,
                content="Retry test message",
                logger=logger,
                max_retries=3,
            )

        assert result is True
        assert channel.send.call_count == 2
        mock_sleep.assert_called_once_with(1)  # First retry delay

    @pytest.mark.asyncio
    async def test_safe_discord_send_max_retries_exceeded(self):
        """Test Discord send when max retries are exceeded."""
        channel = AsyncMock()
        channel.send.side_effect = Exception("Persistent error")

        logger = logging.getLogger("test")

        with patch("asyncio.sleep"):
            result = await safe_discord_send(
                channel=channel,
                content="Failed message",
                logger=logger,
                max_retries=2,
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


@pytest.mark.asyncio
class TestIntegrationScenarios:
    """Test realistic end-to-end integration scenarios."""

    async def test_hybrid_mode_integration_scenario(self, make_request, openai_response):
        """Test a realistic hybrid mode scenario with fallback."""
        conversation_manager = Mock(spec=ThreadSafeConversationManager)
        conversation_manager.get_conversation_summary_formatted.return_value = []

        perplexity_client = Mock()
        perplexity_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Perplexity unavailable")
        )

        openai_client = Mock()
        openai_client.chat.completions.create = AsyncMock(
            return_value=openai_response("Fallback response from OpenAI")
        )

        perplexity_result = await process_perplexity_message(
            make_request("Test web search", conversation_manager=conversation_manager),
            perplexity_client,
            PerplexityConfig(),
        )
        assert perplexity_result is None

        openai_result = await process_openai_message(
            request=make_request(
                "Test fallback",
                conversation_manager=conversation_manager,
            ),
            conversation_summary=[],
            openai_client=openai_client,
            config=OpenAIConfig(
                model="gpt-5-mini",
                system_message="Fallback assistant",
                output_tokens=1000,
            ),
        )
        assert openai_result == "Fallback response from OpenAI"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
