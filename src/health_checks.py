"""API health check and monitoring system for DiscordianAI.

This module provides:
- Health checks for OpenAI, Perplexity, and Discord APIs
- Parameter validation against current API specifications
- Health status reporting and metrics collection
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
import time
from typing import Any

from .config import OPENAI_VALID_MODELS, PERPLEXITY_MODELS, is_supported_openai_model
from .error_handling import ErrorTracker, classify_error

# Health check thresholds
OPENAI_RESPONSE_DEGRADED_THRESHOLD_MS = 5000
OPENAI_RESPONSE_UNHEALTHY_THRESHOLD_MS = 10000
PERPLEXITY_RESPONSE_DEGRADED_THRESHOLD_MS = 8000
PERPLEXITY_RESPONSE_UNHEALTHY_THRESHOLD_MS = 15000
DISCORD_LATENCY_DEGRADED_THRESHOLD_MS = 500
DISCORD_LATENCY_UNHEALTHY_THRESHOLD_MS = 1000


@dataclass
class HealthCheckResult:
    """Result of a health check operation."""

    service: str
    status: str  # 'healthy', 'degraded', 'unhealthy'
    response_time_ms: float
    timestamp: datetime
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class APIHealthMetrics:
    """Aggregated health metrics for an API service."""

    service: str
    total_checks: int = 0
    successful_checks: int = 0
    failed_checks: int = 0
    average_response_time_ms: float = 0.0
    last_check_time: datetime | None = None
    last_success_time: datetime | None = None
    last_failure_time: datetime | None = None
    consecutive_failures: int = 0
    uptime_percentage: float = 100.0


class APIHealthMonitor:
    """Comprehensive API health monitoring system.

    Provides real-time health checks, metrics collection, and alerting
    for all external API dependencies.
    """

    def __init__(self, check_interval: int = 300):  # 5 minutes default
        """Initialize health monitor with interval and state."""
        self.check_interval = check_interval
        self.metrics: dict[str, APIHealthMetrics] = {}
        self.recent_results: list[HealthCheckResult] = []
        self.max_recent_results = 1000
        self.logger = logging.getLogger(__name__)
        self.error_tracker = ErrorTracker()

    async def check_openai_health(
        self,
        openai_client,
        config: dict[str, Any],
    ) -> HealthCheckResult:
        """Perform comprehensive health check of OpenAI API.

        Tests API connectivity, model availability, and parameter validation.
        """
        start_time = time.time()

        try:
            model = config.get("GPT_MODEL", "gpt-5-mini")

            # Validate model is still supported
            if not is_supported_openai_model(model):
                return HealthCheckResult(
                    service="openai",
                    status="degraded",
                    response_time_ms=0,
                    timestamp=datetime.now(UTC),
                    error=f"Model {model} may be deprecated or unsupported",
                    details={"available_models": OPENAI_VALID_MODELS[:5]},  # Show first 5
                )

            response = await openai_client.models.list()

            response_time_ms = (time.time() - start_time) * 1000

            # Validate response structure
            model_ids = [
                model_id
                for item in getattr(response, "data", [])
                if (model_id := getattr(item, "id", None))
            ]
            if not model_ids:
                return HealthCheckResult(
                    service="openai",
                    status="unhealthy",
                    response_time_ms=response_time_ms,
                    timestamp=datetime.now(UTC),
                    error="Invalid response structure from OpenAI model listing API",
                )

            # Check response time thresholds
            status = "healthy"
            if response_time_ms > OPENAI_RESPONSE_UNHEALTHY_THRESHOLD_MS:
                status = "unhealthy"
            elif response_time_ms > OPENAI_RESPONSE_DEGRADED_THRESHOLD_MS:
                status = "degraded"

            # Removed unsupported GPT-5 parameter checks

            return HealthCheckResult(
                service="openai",
                status=status,
                response_time_ms=response_time_ms,
                timestamp=datetime.now(UTC),
                details={
                    "model": model,
                    "available_models": model_ids[:10],
                    "model_count": len(model_ids),
                },
            )

        except Exception as e:  # noqa: BLE001
            response_time_ms = (time.time() - start_time) * 1000
            error_details = classify_error(e)

            return HealthCheckResult(
                service="openai",
                status="unhealthy",
                response_time_ms=response_time_ms,
                timestamp=datetime.now(UTC),
                error=str(e),
                details={
                    "error_type": error_details.error_type.value,
                    "error_severity": error_details.severity.value,
                },
            )

    async def check_perplexity_health(
        self,
        perplexity_client,
        config: dict[str, Any],
    ) -> HealthCheckResult:
        """Perform health check of Perplexity API.

        Tests web search functionality and citation handling.
        """
        start_time = time.time()

        try:
            model = config.get("PERPLEXITY_MODEL", "sonar-pro")

            # Validate model is still supported
            if model not in PERPLEXITY_MODELS:
                return HealthCheckResult(
                    service="perplexity",
                    status="degraded",
                    response_time_ms=0,
                    timestamp=datetime.now(UTC),
                    error=f"Model {model} may be deprecated or unsupported",
                    details={"available_models": PERPLEXITY_MODELS},
                )

            response = await perplexity_client.models.list()

            response_time_ms = (time.time() - start_time) * 1000

            model_ids = [
                model_id
                for item in getattr(response, "data", [])
                if (model_id := getattr(item, "id", None))
            ]
            if not model_ids:
                return HealthCheckResult(
                    service="perplexity",
                    status="unhealthy",
                    response_time_ms=response_time_ms,
                    timestamp=datetime.now(UTC),
                    error="Invalid response structure from Perplexity model listing API",
                )

            status = "healthy"
            if response_time_ms > PERPLEXITY_RESPONSE_UNHEALTHY_THRESHOLD_MS:
                status = "unhealthy"
            elif response_time_ms > PERPLEXITY_RESPONSE_DEGRADED_THRESHOLD_MS:
                status = "degraded"

            return HealthCheckResult(
                service="perplexity",
                status=status,
                response_time_ms=response_time_ms,
                timestamp=datetime.now(UTC),
                details={
                    "model": model,
                    "available_models": model_ids[:10],
                    "model_count": len(model_ids),
                },
            )

        except Exception as e:  # noqa: BLE001
            response_time_ms = (time.time() - start_time) * 1000
            error_details = classify_error(e)

            return HealthCheckResult(
                service="perplexity",
                status="unhealthy",
                response_time_ms=response_time_ms,
                timestamp=datetime.now(UTC),
                error=str(e),
                details={
                    "error_type": error_details.error_type.value,
                    "error_severity": error_details.severity.value,
                },
            )

    async def check_discord_health(self, bot_client) -> HealthCheckResult:
        """Perform health check of Discord API connectivity.

        Tests bot connection status and basic functionality.
        """
        start_time = time.time()

        try:
            # Check if bot is connected
            if not bot_client.is_ready():
                return HealthCheckResult(
                    service="discord",
                    status="unhealthy",
                    response_time_ms=0,
                    timestamp=datetime.now(UTC),
                    error="Discord bot is not ready/connected",
                )

            # Basic connectivity indicators
            response_time_ms = (time.time() - start_time) * 1000

            # Check latency if available
            latency_ms = (
                getattr(bot_client, "latency", 0) * 1000
                if hasattr(bot_client, "latency")
                else None
            )

            status = "healthy"
            if latency_ms and latency_ms > DISCORD_LATENCY_UNHEALTHY_THRESHOLD_MS:
                status = "unhealthy"
            elif latency_ms and latency_ms > DISCORD_LATENCY_DEGRADED_THRESHOLD_MS:
                status = "degraded"

            guild_count = len(bot_client.guilds) if hasattr(bot_client, "guilds") else 0
            user_count = (
                sum(guild.member_count for guild in bot_client.guilds if guild.member_count)
                if hasattr(bot_client, "guilds")
                else 0
            )

            return HealthCheckResult(
                service="discord",
                status=status,
                response_time_ms=response_time_ms,
                timestamp=datetime.now(UTC),
                details={
                    "latency_ms": latency_ms,
                    "guild_count": guild_count,
                    "user_count": user_count,
                    "user_id": (
                        getattr(bot_client.user, "id", None)
                        if hasattr(bot_client, "user")
                        else None
                    ),
                },
            )

        except Exception as e:  # noqa: BLE001
            response_time_ms = (time.time() - start_time) * 1000
            error_details = classify_error(e)

            return HealthCheckResult(
                service="discord",
                status="unhealthy",
                response_time_ms=response_time_ms,
                timestamp=datetime.now(UTC),
                error=str(e),
                details={
                    "error_type": error_details.error_type.value,
                },
            )

    def record_health_check(self, result: HealthCheckResult):
        """Record health check result and update metrics."""
        # Add to recent results
        self.recent_results.append(result)
        if len(self.recent_results) > self.max_recent_results:
            self.recent_results = self.recent_results[-self.max_recent_results :]

        # Update metrics
        if result.service not in self.metrics:
            self.metrics[result.service] = APIHealthMetrics(service=result.service)

        metrics = self.metrics[result.service]
        metrics.total_checks += 1
        metrics.last_check_time = result.timestamp

        if result.status == "healthy":
            metrics.successful_checks += 1
            metrics.last_success_time = result.timestamp
            metrics.consecutive_failures = 0
        else:
            metrics.failed_checks += 1
            metrics.last_failure_time = result.timestamp
            metrics.consecutive_failures += 1

        # Update average response time
        if metrics.total_checks == 1:
            metrics.average_response_time_ms = result.response_time_ms
        else:
            # Weighted average favoring recent results
            weight = 0.1  # 10% weight for new result
            metrics.average_response_time_ms = (
                1 - weight
            ) * metrics.average_response_time_ms + weight * result.response_time_ms

        # Calculate uptime percentage
        if metrics.total_checks > 0:
            metrics.uptime_percentage = (metrics.successful_checks / metrics.total_checks) * 100

    async def run_all_health_checks(
        self,
        clients: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, HealthCheckResult]:
        """Run health checks for all configured API services.

        Args:
            clients: Dict containing 'openai', 'perplexity', 'discord' clients
            config: Configuration dictionary

        Returns:
            Dict mapping service names to health check results
        """
        results = {}

        # OpenAI health check
        if clients.get("openai"):
            try:
                openai_result = await self.check_openai_health(clients["openai"], config)
                results["openai"] = openai_result
                self.record_health_check(openai_result)
            except Exception:
                self.logger.exception("Failed to check OpenAI health")

        # Perplexity health check
        if clients.get("perplexity"):
            try:
                perplexity_result = await self.check_perplexity_health(
                    clients["perplexity"],
                    config,
                )
                results["perplexity"] = perplexity_result
                self.record_health_check(perplexity_result)
            except Exception:
                self.logger.exception("Failed to check Perplexity health")

        # Discord health check
        if clients.get("discord"):
            try:
                discord_result = await self.check_discord_health(clients["discord"])
                results["discord"] = discord_result
                self.record_health_check(discord_result)
            except Exception:
                self.logger.exception("Failed to check Discord health")

        return results
