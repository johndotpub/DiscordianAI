# Tests for smart_orchestrator.py functionality
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.models import AIClients, AIConfig, AIRequest, OpenAIConfig, PerplexityConfig
from src.smart_orchestrator import (
    _process_hybrid_mode,
    _process_openai_only_mode,
    _process_perplexity_only_mode,
    get_smart_response,
    has_time_sensitivity,
    is_conversational_or_creative,
    is_factual_query,
    should_use_web_search,
)


class TestRoutingFunctions:
    def test_has_time_sensitivity_current_events(self):
        """Test time sensitivity detection for current events."""
        assert has_time_sensitivity("What's happening in the news today?")
        assert has_time_sensitivity("Current stock prices for AAPL")
        assert has_time_sensitivity("Latest weather forecast")
        assert has_time_sensitivity("Today's sports scores")

    def test_has_time_sensitivity_no_time_sensitivity(self):
        """Test messages without time sensitivity."""
        assert not has_time_sensitivity("What is Python?")
        assert not has_time_sensitivity("How do I write a function?")
        assert not has_time_sensitivity("Explain quantum mechanics")

    def test_is_factual_query_factual(self):
        """Test factual query detection."""
        assert is_factual_query("What is the capital of France?")
        assert is_factual_query("How many planets are in the solar system?")
        assert is_factual_query("When was Python created?")

    def test_is_factual_query_not_factual(self):
        """Test non-factual queries."""
        assert not is_factual_query("Tell me a story")
        assert not is_factual_query("Write a poem about cats")
        assert not is_factual_query("How are you feeling?")
        assert not is_factual_query("What's your opinion on politics?")

    def test_is_conversational_or_creative_conversational(self):
        """Test conversational/creative content detection."""
        assert is_conversational_or_creative("Tell me a joke")
        assert is_conversational_or_creative("Write a story about dragons")
        assert is_conversational_or_creative("How are you today?")
        assert is_conversational_or_creative("Create a poem")

    def test_is_conversational_or_creative_not_conversational(self):
        """Test non-conversational content."""
        assert not is_conversational_or_creative("What is 2+2?")
        assert not is_conversational_or_creative("Define photosynthesis")
        assert not is_conversational_or_creative("Current weather in London")

    def test_should_use_web_search_time_sensitive(self):
        """Test web search routing for time-sensitive queries."""
        assert should_use_web_search("What's the latest news?")
        assert should_use_web_search("Current stock prices")
        assert should_use_web_search("Today's weather forecast")

    def test_should_use_web_search_factual_with_entities(self):
        """Test web search routing for factual queries with entities."""
        # Long enough message with entities should use web search
        long_factual = (
            "What are the recent developments in artificial intelligence research "
            "and how are they impacting the technology industry?"
        )
        assert should_use_web_search(long_factual)

    def test_should_use_web_search_conversational(self):
        """Test that conversational queries don't use web search."""
        assert not should_use_web_search("Tell me a funny story")
        assert not should_use_web_search("How are you feeling today?")
        assert not should_use_web_search("Write a poem about winter")

    def test_should_use_web_search_with_consistency(self):
        """Test web search function with conversation manager."""
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)

        # Test that function accepts conversation manager parameter
        result = should_use_web_search(
            "What is Python?",
            conversation_manager=conversation_manager,
            user_id=12345,
            lookback_messages=6,
        )

        # Function should complete without error
        assert isinstance(result, bool)

    def test_should_use_web_search_short_message(self):
        """Test that short messages use appropriate routing."""
        short_message = "Hi there"  # Less than default min words
        assert not should_use_web_search(short_message)

    def test_should_use_web_search_consistency_override(self):
        """Test that recent Perplexity usage overrides other heuristic checks."""
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        # Mock that the last service used was Perplexity
        conversation_manager.get_recent_ai_service.return_value = "perplexity"

        # A message that normally wouldn't trigger web search (ambiguous/short)
        message = "tell me more"

        result = should_use_web_search(
            message,
            conversation_manager=conversation_manager,
            user_id=12345,
            lookback_messages=5,
        )

        # Force fail with details if not called, to debug
        if not conversation_manager.get_recent_ai_service.called:
            pytest.fail(
                "conversation_manager.get_recent_ai_service was NOT called. Regex match failed?",
            )

        # Should be True because of consistency
        assert result is True

        # Verify it checked the history
        conversation_manager.get_recent_ai_service.assert_called_with(12345, lookback_messages=5)


class TestProcessingModes:
    @pytest.mark.asyncio
    async def test_process_perplexity_only_mode_success(self):
        """Test successful Perplexity-only processing."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")

        # Mock successful Perplexity response
        perplexity_client = MagicMock()

        # Create models
        request = AIRequest(
            message="Test query",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        ai_config = AIConfig(
            perplexity=PerplexityConfig(system_message="Test system", output_tokens=1000)
        )

        with patch("src.smart_orchestrator.process_perplexity_message") as mock_perplexity:
            mock_perplexity.return_value = ("Perplexity response", True, None)

            response, _suppress_embeds, _embed_data = await _process_perplexity_only_mode(
                request=request,
                perplexity_client=perplexity_client,
                config=ai_config,
            )

            assert response == "Perplexity response"
            assert _suppress_embeds is True
            mock_perplexity.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_perplexity_only_mode_failure(self):
        """Test Perplexity-only mode with API failure."""
        user = MagicMock()
        user.id = 12345

        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")
        perplexity_client = MagicMock()

        # Create models
        request = AIRequest(
            message="Test query",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        ai_config = AIConfig(
            perplexity=PerplexityConfig(system_message="Test system", output_tokens=1000)
        )

        with patch("src.smart_orchestrator.process_perplexity_message") as mock_perplexity:
            mock_perplexity.return_value = None  # Simulate failure

            response, _suppress_embeds, _embed_data = await _process_perplexity_only_mode(
                request=request,
                perplexity_client=perplexity_client,
                config=ai_config,
            )

            # Should return error message from ERROR_MESSAGES
            assert "trouble generating a response" in response
            assert _suppress_embeds is False

    @pytest.mark.asyncio
    async def test_process_openai_only_mode_success(self):
        """Test successful OpenAI-only processing."""
        user = MagicMock()
        user.id = 12345

        conversation_summary = [{"role": "user", "content": "Hello"}]
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")
        openai_client = MagicMock()

        # Create models
        request = AIRequest(
            message="Test query",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        ai_config = AIConfig(openai=OpenAIConfig(system_message="Test system", output_tokens=1000))

        with patch("src.smart_orchestrator.process_openai_message") as mock_openai:
            mock_openai.return_value = "OpenAI response"

            response, _suppress_embeds, _embed_data = await _process_openai_only_mode(
                request=request,
                conversation_summary=conversation_summary,
                openai_client=openai_client,
                config=ai_config,
            )

            assert response == "OpenAI response"
            assert _suppress_embeds is False
            mock_openai.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_openai_only_mode_failure(self):
        """Test OpenAI-only mode with API failure."""
        user = MagicMock()
        conversation_summary = []
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")
        openai_client = MagicMock()

        # Create models
        request = AIRequest(
            message="Test query",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        ai_config = AIConfig(openai=OpenAIConfig(system_message="Test system", output_tokens=1000))

        with patch("src.smart_orchestrator.process_openai_message") as mock_openai:
            mock_openai.return_value = None  # Simulate failure

            response, _suppress_embeds, _embed_data = await _process_openai_only_mode(
                request=request,
                conversation_summary=conversation_summary,
                openai_client=openai_client,
                config=ai_config,
            )

            # Should return error message from ERROR_MESSAGES
            assert "trouble generating a response" in response
            assert _suppress_embeds is False

    @pytest.mark.asyncio
    async def test_process_hybrid_mode_web_search_preferred(self):
        """Test hybrid mode choosing web search."""
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")
        openai_client = MagicMock()
        perplexity_client = MagicMock()

        request = AIRequest(
            message="What's the latest news?",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        clients = AIClients(openai=openai_client, perplexity=perplexity_client)
        ai_config = AIConfig()

        with (
            patch("src.smart_orchestrator.should_use_web_search", return_value=True),
            patch("src.smart_orchestrator.process_perplexity_message") as mock_perplexity,
            patch("src.smart_orchestrator.process_openai_message") as mock_openai,
        ):
            mock_perplexity.return_value = ("Web search result", True, None)

            response, _suppress_embeds, _embed_data = await _process_hybrid_mode(
                request=request,
                conversation_summary=[],
                clients=clients,
                config=ai_config,
            )

            assert response == "Web search result"
            assert _suppress_embeds is True
            mock_perplexity.assert_called_once()
            mock_openai.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_hybrid_mode_basic(self):
        """Test hybrid mode basic functionality."""
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")
        openai_client = MagicMock()
        perplexity_client = MagicMock()

        request = AIRequest(
            message="Test message",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        clients = AIClients(openai=openai_client, perplexity=perplexity_client)
        ai_config = AIConfig()

        response, _suppress_embeds, _embed_data = await _process_hybrid_mode(
            request=request,
            conversation_summary=[],
            clients=clients,
            config=ai_config,
        )

        assert response is not None
        assert isinstance(_suppress_embeds, bool)

    @pytest.mark.asyncio
    async def test_process_hybrid_mode_fallback_chain(self):
        """Test full fallback chain: Perplexity fails -> OpenAI handles it."""
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")
        openai_client = MagicMock()
        perplexity_client = MagicMock()

        request = AIRequest(
            message="Complex query",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        clients = AIClients(openai=openai_client, perplexity=perplexity_client)
        ai_config = AIConfig()

        with (
            patch("src.smart_orchestrator.should_use_web_search", return_value=True),
            patch("src.smart_orchestrator.process_perplexity_message", return_value=None),
            patch("src.smart_orchestrator.process_openai_message") as mock_openai,
        ):
            mock_openai.return_value = "OpenAI fallback response"

            response, _suppress_embeds, _embed_data = await _process_hybrid_mode(
                request=request,
                conversation_summary=[],
                clients=clients,
                config=ai_config,
            )

            assert response == "OpenAI fallback response"
            mock_openai.assert_called_once()


class TestMainOrchestrator:
    @pytest.mark.asyncio
    async def test_get_smart_response_hybrid_mode(self):
        """Test main orchestrator function in hybrid mode."""
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")
        openai_client = MagicMock()
        perplexity_client = MagicMock()

        request = AIRequest(
            message="Test message",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        clients = AIClients(openai=openai_client, perplexity=perplexity_client)
        ai_config = AIConfig()

        with patch("src.smart_orchestrator._process_hybrid_mode") as mock_hybrid:
            mock_hybrid.return_value = ("Hybrid response", True, None)

            response, _suppress_embeds, _embed_data = await get_smart_response(
                request=request,
                conversation_summary=[],
                clients=clients,
                config=ai_config,
            )

            assert response == "Hybrid response"
            assert _suppress_embeds is True
            mock_hybrid.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_smart_response_openai_only(self):
        """Test main orchestrator with only OpenAI available."""
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")
        openai_client = MagicMock()
        perplexity_client = None

        request = AIRequest(
            message="Test message",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        clients = AIClients(openai=openai_client, perplexity=perplexity_client)
        ai_config = AIConfig()

        with patch("src.smart_orchestrator._process_openai_only_mode") as mock_openai:
            mock_openai.return_value = ("OpenAI only response", False, None)

            response, _suppress_embeds, _embed_data = await get_smart_response(
                request=request,
                conversation_summary=[],
                clients=clients,
                config=ai_config,
            )

            assert response == "OpenAI only response"
            assert _suppress_embeds is False
            mock_openai.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_smart_response_perplexity_only(self):
        """Test main orchestrator with only Perplexity available."""
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")
        openai_client = None
        perplexity_client = MagicMock()

        request = AIRequest(
            message="Test message",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        clients = AIClients(openai=openai_client, perplexity=perplexity_client)
        ai_config = AIConfig()

        with patch("src.smart_orchestrator._process_perplexity_only_mode") as mock_perplexity:
            mock_perplexity.return_value = ("Perplexity only response", True, None)

            response, _suppress_embeds, _embed_data = await get_smart_response(
                request=request,
                conversation_summary=[],
                clients=clients,
                config=ai_config,
            )

            assert response == "Perplexity only response"
            assert _suppress_embeds is True
            mock_perplexity.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_smart_response_no_clients(self):
        """Test orchestrator with no API clients available."""
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")

        request = AIRequest(
            message="Test message",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        clients = AIClients(openai=None, perplexity=None)
        ai_config = AIConfig()

        response, _suppress_embeds, _embed_data = await get_smart_response(
            request=request,
            conversation_summary=[],
            clients=clients,
            config=ai_config,
        )

        # Should return configuration error
        assert "AI services are not properly configured" in response
        assert _suppress_embeds is False
