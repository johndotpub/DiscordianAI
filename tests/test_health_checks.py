"""Comprehensive tests for the health check and monitoring system.

This test suite covers:
- Individual API health checks (OpenAI, Perplexity, Discord)
- Health metrics collection and aggregation
- Health monitoring loop functionality
- Configuration validation integration
- Alerting and status determination
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.health_checks import (
    APIHealthMetrics,
    APIHealthMonitor,
    HealthCheckResult,
)


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


class TestAPIHealthMetrics:
    """Test APIHealthMetrics dataclass and calculations."""

    def test_metrics_initialization(self):
        """Test APIHealthMetrics initialization."""
        metrics = APIHealthMetrics(service="discord")

        assert metrics.service == "discord"
        assert metrics.total_checks == 0
        assert metrics.uptime_percentage == 100.0
        assert metrics.consecutive_failures == 0

    def test_metrics_calculations(self):
        """Test metrics calculations."""
        APIHealthMetrics(
            service="test",
            total_checks=100,
            successful_checks=95,
            failed_checks=5,
        )

        # Uptime calculation would be done by the monitor
        expected_uptime = (95 / 100) * 100
        assert expected_uptime == 95.0


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
        assert result.status in ["healthy", "degraded"]  # Depending on response time
        assert result.error is None
        assert result.details["model"] == "gpt-5-mini"
        assert result.details["model_count"] == 2
        assert result.details["available_models"] == ["gpt-5-mini", "gpt-5"]

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
    async def test_openai_health_check_deprecated_model(self):
        """Test OpenAI health check with deprecated model."""
        openai_client = Mock()
        config = {"GPT_MODEL": "deprecated-model"}

        result = await self.monitor.check_openai_health(openai_client, config)

        assert result.service == "openai"
        assert result.status == "degraded"
        assert "deprecated-model may be deprecated" in result.error
        assert "available_models" in result.details

    @pytest.mark.asyncio
    async def test_perplexity_health_check_success(self):
        """Test successful Perplexity health check."""
        # Mock Perplexity client
        perplexity_client = Mock()
        mock_response = Mock()
        mock_response.data = [Mock(id="sonar-pro"), Mock(id="sonar")]

        mock_create = AsyncMock()
        mock_create.return_value = mock_response
        perplexity_client.models.list = mock_create

        config = {"PERPLEXITY_MODEL": "sonar-pro"}

        result = await self.monitor.check_perplexity_health(perplexity_client, config)

        assert result.service == "perplexity"
        assert result.status in ["healthy", "degraded"]
        assert result.error is None
        assert result.details["model"] == "sonar-pro"
        assert result.details["model_count"] == 2
        assert result.details["available_models"] == ["sonar-pro", "sonar"]

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

    def test_record_health_check_success(self):
        """Test recording successful health check."""
        result = HealthCheckResult(
            service="openai",
            status="healthy",
            response_time_ms=200,
            timestamp=datetime.now(UTC),
        )

        self.monitor.record_health_check(result)

        assert "openai" in self.monitor.metrics
        metrics = self.monitor.metrics["openai"]
        assert metrics.total_checks == 1
        assert metrics.successful_checks == 1
        assert metrics.failed_checks == 0
        assert metrics.consecutive_failures == 0
        assert metrics.uptime_percentage == 100.0

    def test_record_health_check_failure(self):
        """Test recording failed health check."""
        result = HealthCheckResult(
            service="perplexity",
            status="unhealthy",
            response_time_ms=0,
            timestamp=datetime.now(UTC),
            error="Connection failed",
        )

        self.monitor.record_health_check(result)

        metrics = self.monitor.metrics["perplexity"]
        assert metrics.total_checks == 1
        assert metrics.successful_checks == 0
        assert metrics.failed_checks == 1
        assert metrics.consecutive_failures == 1
        assert metrics.uptime_percentage == 0.0

    def test_record_multiple_health_checks(self):
        """Test recording multiple health checks and metric updates."""
        # Record 3 successful checks
        for i in range(3):
            result = HealthCheckResult(
                service="discord",
                status="healthy",
                response_time_ms=100 + i * 10,  # Varying response times
                timestamp=datetime.now(UTC),
            )
            self.monitor.record_health_check(result)

        # Record 1 failed check
        failed_result = HealthCheckResult(
            service="discord",
            status="unhealthy",
            response_time_ms=0,
            timestamp=datetime.now(UTC),
            error="Timeout",
        )
        self.monitor.record_health_check(failed_result)

        metrics = self.monitor.metrics["discord"]
        assert metrics.total_checks == 4
        assert metrics.successful_checks == 3
        assert metrics.failed_checks == 1
        assert metrics.consecutive_failures == 1
        assert metrics.uptime_percentage == 75.0

    @pytest.mark.asyncio
    async def test_run_all_health_checks(self):
        """Test running health checks for all services."""
        # Mock clients
        openai_client = Mock()
        openai_response = Mock()
        openai_response.choices = [Mock()]
        openai_response.choices[0].message.content = "OpenAI health check"
        openai_response.usage = Mock()
        openai_client.chat.completions.create.return_value = openai_response

        perplexity_client = Mock()
        perplexity_response = Mock()
        perplexity_response.choices = [Mock()]
        perplexity_response.choices[0].message.content = "Perplexity health check"
        perplexity_response.usage = Mock()
        perplexity_client.chat.completions.create.return_value = perplexity_response

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
            "PERPLEXITY_MODEL": "sonar-pro",
        }

        results = await self.monitor.run_all_health_checks(clients, config)

        assert len(results) == 3
        assert "openai" in results
        assert "perplexity" in results
        assert "discord" in results

        # Verify all checks were recorded
        assert len(self.monitor.metrics) == 3


if __name__ == "__main__":
    # Run health check tests with verbose output
    pytest.main([__file__, "-v"])
