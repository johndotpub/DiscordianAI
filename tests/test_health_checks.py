"""Comprehensive tests for the health check and monitoring system.

This test suite covers:
- Individual API health checks (OpenAI, Perplexity, Discord)
- Provider probe wiring and status classification
- Health monitoring loop functionality
- Configuration validation integration
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.health_checks import APIHealthMonitor, HealthCheckResult
from src.providers.base import ProbeResult
from src.providers.openai_chat import ChatCompletionsProvider


class TestHealthCheckResult:
    """Test HealthCheckResult dataclass."""

    def test_health_check_result_creation(self):
        """Test creating a HealthCheckResult."""
        result = HealthCheckResult(
            service="openai",
            status="healthy",
            response_time_ms=150.5,
            timestamp=datetime.now(UTC),
            details={"model": "gpt-5-mini"},
        )

        assert result.service == "openai"
        assert result.status == "healthy"
        assert result.response_time_ms == 150.5
        assert result.details["model"] == "gpt-5-mini"
        assert result.error is None

    def test_health_check_result_with_error(self):
        """Test creating a HealthCheckResult with error."""
        result = HealthCheckResult(
            service="perplexity",
            status="unhealthy",
            response_time_ms=0,
            timestamp=datetime.now(UTC),
            error="Connection timeout",
        )

        assert result.service == "perplexity"
        assert result.status == "unhealthy"
        assert result.error == "Connection timeout"


class TestAPIHealthMonitor:
    """Test the main APIHealthMonitor class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.monitor = APIHealthMonitor(check_interval=10)  # Short interval for tests

    @pytest.mark.asyncio
    async def test_openai_health_check_success(self):
        """Test successful OpenAI health check."""
        # Mock OpenAI client
        openai_client = Mock()
        mock_response = Mock()
        mock_response.data = [Mock(id="gpt-5-mini"), Mock(id="gpt-5")]

        mock_create = AsyncMock()
        mock_create.return_value = mock_response
        openai_client.models.list = mock_create

        config = {"GPT_MODEL": "gpt-5-mini"}

        result = await self.monitor.check_openai_health(openai_client, config)

        assert result.service == "openai"
        assert result.status == "healthy"
        assert result.error is None
        assert result.details["model"] == "gpt-5-mini"
        assert result.details["probe"] == "2 models available"

    @pytest.mark.asyncio
    async def test_openai_health_check_failure(self):
        """Test OpenAI health check with API failure."""
        # Mock OpenAI client that raises exception
        openai_client = Mock()
        openai_client.models.list.side_effect = Exception("API unavailable")

        config = {"GPT_MODEL": "gpt-5-mini"}

        result = await self.monitor.check_openai_health(openai_client, config)

        assert result.service == "openai"
        assert result.status == "unhealthy"
        assert "API unavailable" in result.error
        assert "error_type" in result.details

    @pytest.mark.asyncio
    async def test_openai_health_check_accepts_any_non_empty_model(self):
        """A non-empty provider model id is not treated as deprecated."""
        openai_client = Mock()
        response = Mock()
        response.data = [Mock(id="deepseek-v4.1-flash:1017")]
        openai_client.models.list = AsyncMock(return_value=response)
        config = {"GPT_MODEL": "deprecated-model"}

        result = await self.monitor.check_openai_health(openai_client, config)

        assert result.service == "openai"
        assert result.status == "healthy"
        assert result.details["model"] == "deprecated-model"

    @pytest.mark.asyncio
    async def test_openai_health_check_flags_an_empty_model(self):
        """An empty model id cannot be checked against the provider."""
        openai_client = Mock()
        config = {"GPT_MODEL": ""}

        result = await self.monitor.check_openai_health(openai_client, config)

        assert result.service == "openai"
        assert result.status == "degraded"
        assert "may be deprecated" in result.error
        assert "available_models" in result.details

    @pytest.mark.asyncio
    async def test_perplexity_health_check_success(self):
        """Test successful Perplexity health check."""
        # Mock Perplexity client
        perplexity_client = Mock()
        mock_response = Mock()
        mock_response.data = [Mock(id="perplexity/sonar"), Mock(id="other-model")]

        mock_create = AsyncMock()
        mock_create.return_value = mock_response
        perplexity_client.models.list = mock_create

        config = {"PERPLEXITY_MODEL": "perplexity/sonar"}

        result = await self.monitor.check_perplexity_health(perplexity_client, config)

        assert result.service == "perplexity"
        assert result.status == "healthy"
        assert result.error is None
        assert result.details["model"] == "perplexity/sonar"
        assert result.details["probe"] == "2 models available"

        # Verify that the API call was made successfully
        perplexity_client.models.list.assert_called_once()
        # Citations are now included by default, no special parameters needed

    @pytest.mark.asyncio
    async def test_discord_health_check_success(self):
        """Test successful Discord health check."""
        # Mock Discord bot client
        bot_client = Mock()
        bot_client.is_ready.return_value = True
        bot_client.latency = 0.1  # 100ms latency
        bot_client.guilds = [Mock(), Mock()]  # 2 guilds
        bot_client.guilds[0].member_count = 100
        bot_client.guilds[1].member_count = 200
        bot_client.user = Mock()
        bot_client.user.id = 12345

        result = await self.monitor.check_discord_health(bot_client)

        assert result.service == "discord"
        assert result.status == "healthy"
        assert result.error is None
        assert result.details["latency_ms"] == 100.0
        assert result.details["guild_count"] == 2
        assert result.details["user_count"] == 300

    @pytest.mark.asyncio
    async def test_discord_health_check_not_ready(self):
        """Test Discord health check when bot is not ready."""
        bot_client = Mock()
        bot_client.is_ready.return_value = False

        result = await self.monitor.check_discord_health(bot_client)

        assert result.service == "discord"
        assert result.status == "unhealthy"
        assert "not ready" in result.error

    @pytest.mark.asyncio
    async def test_run_all_health_checks(self):
        """Every configured service is checked through the method it really calls."""
        openai_client = Mock()
        openai_client.models.list = AsyncMock(return_value=Mock(data=[Mock(id="gpt-5-mini")]))

        perplexity_client = Mock()
        perplexity_client.models.list = AsyncMock(
            return_value=Mock(data=[Mock(id="perplexity/sonar")])
        )

        discord_client = Mock()
        discord_client.is_ready.return_value = True
        discord_client.latency = 0.05
        discord_client.guilds = []
        discord_client.user = Mock()
        discord_client.user.id = 54321

        clients = {
            "openai": openai_client,
            "perplexity": perplexity_client,
            "discord": discord_client,
        }

        config = {
            "GPT_MODEL": "gpt-5-mini",
            "PERPLEXITY_MODEL": "perplexity/sonar",
        }

        results = await self.monitor.run_all_health_checks(clients, config)

        assert len(results) == 3
        assert results["openai"].status == "healthy"
        assert results["perplexity"].status == "healthy"
        assert results["discord"].status == "healthy"
        assert results["openai"].details["model"] == "gpt-5-mini"


@pytest.mark.asyncio
async def test_health_check_uses_the_provider_probe(monkeypatch):
    """Health checks call the adapter's bounded probe instead of models.list."""
    probed = []

    async def fake_probe(provider):
        probed.append(provider._client)
        return ProbeResult(ok=True, detail="1 models available", latency_ms=1.0)

    monkeypatch.setattr(ChatCompletionsProvider, "probe", fake_probe)
    monitor = APIHealthMonitor()
    client = Mock()
    client.models.list = AsyncMock(return_value=Mock(data=[Mock(id="gpt-5-mini")]))

    result = await monitor.check_openai_health(client, {"GPT_MODEL": "gpt-5-mini"})

    assert probed == [client]
    assert result.status == "healthy"


if __name__ == "__main__":
    # Run health check tests with verbose output
    pytest.main([__file__, "-v"])
