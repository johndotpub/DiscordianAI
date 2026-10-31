# Tests for smart_orchestrator.py functionality
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.models import AIClients, AIConfig, AIRequest, OpenAIConfig, PerplexityConfig
from src.routing import HeuristicRouter
from src.routing.context import build_router_input
from src.routing.contracts import RouterInput
from src.smart_orchestrator import (
    _process_hybrid_mode,
    _process_openai_only_mode,
    _process_perplexity_only_mode,
    _sanitize_for_routing,
    get_smart_response,
)


class TestSanitizeForRouting:
    """Tests for _sanitize_for_routing() — Discord markup stripping for routing only."""

    def test_strips_custom_emoji(self):
        msg = "How's your brain feeling? <a:HACKERMANS:123456789>"
        assert "HACKERMANS" not in _sanitize_for_routing(msg)
        assert "How's your brain feeling?" in _sanitize_for_routing(msg)

    def test_strips_static_emoji(self):
        msg = "Goodnight <:cheers:987654321>"
        assert "cheers" not in _sanitize_for_routing(msg)
        assert "Goodnight" in _sanitize_for_routing(msg)

    def test_strips_user_mentions(self):
        msg = "<@123456789> what's up?"
        assert "<@" not in _sanitize_for_routing(msg)
        assert "what's up?" in _sanitize_for_routing(msg)

    def test_strips_user_mentions_with_bang(self):
        msg = "<@!123456789> hello"
        assert "<@!" not in _sanitize_for_routing(msg)
        assert "hello" in _sanitize_for_routing(msg)

    def test_strips_role_mentions(self):
        msg = "<@&111222333> check this"
        assert "<@&" not in _sanitize_for_routing(msg)
        assert "check this" in _sanitize_for_routing(msg)

    def test_strips_channel_mentions(self):
        msg = "See <#444555666> for details"
        assert "<#" not in _sanitize_for_routing(msg)
        assert "See for details" in _sanitize_for_routing(msg)

    def test_strips_timestamps(self):
        msg = "Event at <t:1234567890>"
        assert "<t:" not in _sanitize_for_routing(msg)
        assert "Event at" in _sanitize_for_routing(msg)

    def test_strips_timestamps_with_style(self):
        msg = "Due <t:1234567890:R> soon"
        assert "<t:" not in _sanitize_for_routing(msg)
        assert "Due soon" in _sanitize_for_routing(msg)

    def test_strips_multiple_markup_types(self):
        msg = "<@123> Hey <a:HACKERMANS:456> check <#789> at <t:1000:F>"
        result = _sanitize_for_routing(msg)
        assert "HACKERMANS" not in result
        assert "<@" not in result
        assert "<#" not in result
        assert "<t:" not in result
        assert "Hey" in result
        assert "check" in result
        assert "at" in result

    def test_collapses_whitespace(self):
        msg = "Hello   <a:test:123>   world"
        result = _sanitize_for_routing(msg)
        assert "  " not in result
        assert "Hello world" in result

    def test_preserves_plain_text(self):
        msg = "What's the weather today?"
        assert _sanitize_for_routing(msg) == msg

    def test_empty_string(self):
        assert _sanitize_for_routing("") == ""

    def test_emoji_name_no_longer_triggers_entity(self):
        """The root cause of HACKERMANS misroute — uppercase emoji names."""
        msg = "Going to bed <a:HACKERMANS:123456789>"
        sanitized = _sanitize_for_routing(msg)
        decision = HeuristicRouter().decide_sync(RouterInput(text=sanitized))
        assert decision.route == "local"

    def test_now_in_plain_text_still_works(self):
        """Sanitization should not affect non-markup text."""
        msg = "What is happening right now in the stock market?"
        # 'now' is still present — sanitization doesn't touch plain text
        assert "now" in _sanitize_for_routing(msg)


class TestRoutingBehaviour:
    """Routing decisions are exercised through the real heuristic router."""

    @staticmethod
    def _route(message: str) -> str:
        return HeuristicRouter().decide_sync(RouterInput(text=message)).route

    def test_time_sensitive_queries_route_to_web(self):
        assert self._route("What's the latest news?") == "web"
        assert self._route("Current stock prices") == "web"
        assert self._route("Today's weather forecast") == "web"
        assert self._route("What's happening right now?") == "web"

    def test_standalone_now_is_not_time_sensitive(self):
        assert self._route("Now you're just fucking with me.") == "local"

    def test_conversational_and_creative_queries_stay_local(self):
        assert self._route("Tell me a funny story") == "local"
        assert self._route("How are you feeling?") == "local"
        assert self._route("Write a poem about winter") == "local"
        assert self._route("Hi there") == "local"

    def test_explicit_web_instruction_routes_to_web(self):
        assert self._route("Please search the web for best laptops") == "web"
        assert self._route("Search the internet for the population of Japan") == "web"

    def test_entity_only_question_stays_local_under_the_bearing_gate(self):
        assert self._route("Tell me about John Doe") == "local"
        assert self._route("HACKERMANS is a cool emoji") == "local"

    def test_stock_shape_routes_to_web(self):
        assert self._route("What's $AAPL trading at right now?") == "web"
        assert self._route("We use JSON for serialization") == "local"

    def test_follow_up_inherits_perplexity_from_conversation(self):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        conversation_manager.get_recent_ai_service.return_value = "perplexity"
        request = AIRequest(
            message="tell me more",
            user=MagicMock(id=12345),
            conversation_manager=conversation_manager,
            logger=logging.getLogger("test"),
            conversation_key="dm:12345",
        )

        router_input = build_router_input(request, conversation_manager, 5)
        decision = HeuristicRouter().decide_sync(router_input)

        assert decision.route == "web"
        conversation_manager.get_recent_ai_service.assert_called_with(
            "dm:12345", lookback_messages=5
        )

    def test_follow_up_without_history_stays_local(self):
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        conversation_manager.get_recent_ai_service.return_value = None
        request = AIRequest(
            message="tell me more",
            user=MagicMock(id=999),
            conversation_manager=conversation_manager,
            logger=logging.getLogger("test"),
            conversation_key="dm:999",
        )

        router_input = build_router_input(request, conversation_manager, 3)
        decision = HeuristicRouter().decide_sync(router_input)

        assert decision.route == "local"

    @pytest.mark.asyncio
    async def test_openai_web_inability_reroute_logs(self, caplog):
        """Hybrid mode logs reroute when OpenAI indicates web-inability."""
        caplog.set_level(logging.INFO, logger="src.smart_orchestrator")

        cm = MagicMock()
        user = MagicMock()
        user.id = 1
        logger = logging.getLogger("src.smart_orchestrator.test")
        request = AIRequest("What is the capital of France?", user, cm, logger)

        clients = AIClients(openai=object(), perplexity=object())
        cfg = AIConfig()

        async def fake_openai(req, conv, client, cfg):
            return "Sorry, I can't access the internet to look that up."

        async def fake_perp(req, client, cfg, conversation_summary=None):
            return ("Perplexity result", False, None)

        with (
            patch("src.smart_orchestrator.process_openai_message", fake_openai),
            patch("src.smart_orchestrator.process_perplexity_message", fake_perp),
        ):
            await _process_hybrid_mode(request, [], clients, cfg, orchestrator_config=None)

        msgs = [r.getMessage() for r in caplog.records]
        assert any("rerouting to Perplexity" in m or "Routing to Perplexity" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_reroute_log_does_not_dump_the_discarded_answer(self, caplog):
        """A reroute logs the answer length, never the whole answer."""
        caplog.set_level(logging.DEBUG)

        cm = MagicMock()
        user = MagicMock()
        user.id = 7
        logger = logging.getLogger("src.smart_orchestrator.test")
        request = AIRequest("What is the capital of France?", user, cm, logger)

        clients = AIClients(openai=object(), perplexity=object())
        cfg = AIConfig()
        marker = "UNIQUE_REROUTE_MARKER_" + ("x" * 1980)
        answer = f"I can't access the internet. {marker}"

        async def fake_openai(req, conv, client, cfg):
            return answer

        async def fake_perp(req, client, cfg, conversation_summary=None):
            return ("Perplexity result", False, None)

        with (
            patch("src.smart_orchestrator.process_openai_message", fake_openai),
            patch("src.smart_orchestrator.process_perplexity_message", fake_perp),
        ):
            await _process_hybrid_mode(request, [], clients, cfg, orchestrator_config=None)

        reroute_records = [
            record
            for record in caplog.records
            if "Discarding OpenAI answer" in record.getMessage()
        ]
        assert reroute_records, "Expected a debug line for the discarded answer"
        logged = reroute_records[0].getMessage()
        assert marker not in logged
        assert len(logged) < 300
        assert str(len(answer)) in logged

    @pytest.mark.asyncio
    async def test_perplexity_fallback_logs(self, caplog):
        """If Perplexity fails initially, hybrid mode logs fallback to OpenAI."""
        caplog.set_level(logging.INFO, logger="src.smart_orchestrator")

        cm = MagicMock()
        user = MagicMock()
        user.id = 2
        logger = logging.getLogger("src.smart_orchestrator.test")
        request = AIRequest("http://example.com/page", user, cm, logger)

        clients = AIClients(openai=object(), perplexity=object())
        cfg = AIConfig()

        async def failing_perp(req, client, cfg, conversation_summary=None):
            return None

        async def success_openai(req, conv, client, cfg):
            return "OpenAI fallback response"

        with (
            patch("src.smart_orchestrator.process_perplexity_message", failing_perp),
            patch("src.smart_orchestrator.process_openai_message", success_openai),
        ):
            await _process_hybrid_mode(request, [], clients, cfg, orchestrator_config=None)

        msgs = [r.getMessage() for r in caplog.records]
        assert any("falling back to OpenAI" in m for m in msgs), "Expected Perplexity fallback log"


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
            conversation_manager.add_message.assert_any_call(12345, "user", "Test query")
            conversation_manager.add_message.assert_any_call(
                12345,
                "assistant",
                "Perplexity response",
                metadata={"ai_service": "perplexity", "model": "perplexity/sonar"},
            )
            assert conversation_manager.add_message.call_count == 2

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
            conversation_manager.add_message.assert_any_call(12345, "user", "Test query")
            conversation_manager.add_message.assert_any_call(
                12345,
                "assistant",
                "OpenAI response",
                metadata={"ai_service": "openai", "model": "gpt-6-luna"},
            )
            assert conversation_manager.add_message.call_count == 2

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
            conversation_manager.add_message.assert_any_call(
                12345, "user", "What's the latest news?"
            )
            conversation_manager.add_message.assert_any_call(
                12345,
                "assistant",
                "Web search result",
                metadata={"ai_service": "perplexity", "model": "perplexity/sonar"},
            )
            assert conversation_manager.add_message.call_count == 2

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

        with patch(
            "src.smart_orchestrator.process_openai_message",
            return_value="OpenAI response",
        ) as mock_openai:
            response, _suppress_embeds, _embed_data = await _process_hybrid_mode(
                request=request,
                conversation_summary=[],
                clients=clients,
                config=ai_config,
            )

        assert response == "OpenAI response"
        assert _suppress_embeds is False
        assert _embed_data is None
        mock_openai.assert_awaited_once()
        conversation_manager.add_message.assert_any_call(
            12345,
            "assistant",
            "OpenAI response",
            metadata={"ai_service": "openai", "model": "gpt-6-luna"},
        )
        assert conversation_manager.add_message.call_count == 2

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
            message="http://example.com/status",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        clients = AIClients(openai=openai_client, perplexity=perplexity_client)
        ai_config = AIConfig()

        with (
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
            conversation_manager.add_message.assert_any_call(
                12345, "user", "http://example.com/status"
            )
            conversation_manager.add_message.assert_any_call(
                12345,
                "assistant",
                "OpenAI fallback response",
                metadata={"ai_service": "openai", "model": "gpt-6-luna"},
            )
            assert conversation_manager.add_message.call_count == 2

    @pytest.mark.asyncio
    async def test_openai_web_inability_triggers_perplexity_reroute(self):
        """If OpenAI responds with a web-inability message, reroute to Perplexity."""
        user = MagicMock()
        user.id = 12345
        conversation_manager = MagicMock(spec=ThreadSafeConversationManager)
        logger = logging.getLogger("test")
        openai_client = MagicMock()
        perplexity_client = MagicMock()

        request = AIRequest(
            message="What is the capital of France?",
            user=user,
            conversation_manager=conversation_manager,
            logger=logger,
        )
        clients = AIClients(openai=openai_client, perplexity=perplexity_client)
        ai_config = AIConfig()

        with (
            patch("src.smart_orchestrator.process_openai_message") as mock_openai,
            patch("src.smart_orchestrator.process_perplexity_message") as mock_perplexity,
        ):
            # OpenAI returns a message saying it can't access the internet
            mock_openai.return_value = (
                "Sorry, I don't have access to the internet to look that up."
            )
            mock_perplexity.return_value = ("Perplexity result", True, None)

            response, _suppress_embeds, _embed_data = await _process_hybrid_mode(
                request=request,
                conversation_summary=[],
                clients=clients,
                config=ai_config,
            )

            # Should have used Perplexity after detecting web-inability
            assert response == "Perplexity result"
            mock_perplexity.assert_called_once()
            conversation_manager.add_message.assert_any_call(
                12345, "user", "What is the capital of France?"
            )
            conversation_manager.add_message.assert_any_call(
                12345,
                "assistant",
                "Perplexity result",
                metadata={"ai_service": "perplexity", "model": "perplexity/sonar"},
            )
            assert conversation_manager.add_message.call_count == 2


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
