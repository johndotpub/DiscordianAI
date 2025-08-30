"""API health check and monitoring system for DiscordianAI.

This module provides:
- Health checks for OpenAI, Perplexity, and Discord APIs
- Parameter validation against current API specifications
- Proactive monitoring and alerting for API issues
- Health status reporting and metrics collection
"""

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import time
from typing import Any

from .api_validation import (
    OPENAI_VALID_MODELS,
    PERPLEXITY_MODELS,
    validate_full_config,
)
from .error_handling import ErrorTracker, classify_error


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
        self._monitoring_active = False
        self._monitor_task: asyncio.Task | None = None

    async def check_openai_health(
        self, openai_client, config: dict[str, Any]
    ) -> HealthCheckResult:
        """Perform comprehensive health check of OpenAI API.

        Tests API connectivity, model availability, and parameter validation.
        """
        start_time = time.time()

        try:
            # Test basic API connectivity with minimal request
            test_messages = [
                {"role": "system", "content": "Health check"},
                {"role": "user", "content": "ping"},
            ]

            model = config.get("GPT_MODEL", "gpt-5-mini")

            # Validate model is still supported
            if model not in OPENAI_VALID_MODELS:
                return HealthCheckResult(
                    service="openai",
                    status="degraded",
                    response_time_ms=0,
                    timestamp=datetime.now(timezone.utc),
                    error=f"Model {model} may be deprecated or unsupported",
                    details={"available_models": OPENAI_VALID_MODELS[:5]},  # Show first 5
                )

            # Make minimal API call
            # Use appropriate token parameter based on model
            api_params = {
                "model": model,
                "messages": test_messages,
                "timeout": 30,  # Quick timeout for health check
            }

            # GPT-5 models use max_completion_tokens
            api_params["max_completion_tokens"] = 10  # Minimal response

            response = await asyncio.to_thread(
                lambda: openai_client.chat.completions.create(**api_params)
            )

            response_time_ms = (time.time() - start_time) * 1000

            # Validate response structure
            if not response or not response.choices or not response.choices[0].message.content:
                return HealthCheckResult(
                    service="openai",
                    status="unhealthy",
                    response_time_ms=response_time_ms,
                    timestamp=datetime.now(timezone.utc),
                    error="Invalid response structure from OpenAI API",
                )

            # Check response time thresholds
            status = "healthy"
            if response_time_ms > 5000:  # 5 seconds
                status = "degraded"
            elif response_time_ms > 10000:  # 10 seconds
                status = "unhealthy"

            # Removed unsupported GPT-5 parameter checks

            return HealthCheckResult(
                service="openai",
                status=status,
                response_time_ms=response_time_ms,
                timestamp=datetime.now(timezone.utc),
                details={
                    "model": model,
                    "response_id": getattr(response, "id", "unknown"),
                    "usage": (
                        getattr(response, "usage", {}).__dict__
                        if hasattr(response, "usage")
                        else {}
                    ),
                },
            )

        except Exception as e:  # noqa: BLE001 - health check should never crash callers
            response_time_ms = (time.time() - start_time) * 1000
            error_details = classify_error(e)

            return HealthCheckResult(
                service="openai",
                status="unhealthy",
                response_time_ms=response_time_ms,
                timestamp=datetime.now(timezone.utc),
                error=str(e),
                details={
                    "error_type": error_details.error_type.value,
                    "error_severity": error_details.severity.value,
                },
            )

    async def check_perplexity_health(
        self, perplexity_client, config: dict[str, Any]
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
                    timestamp=datetime.now(timezone.utc),
                    error=f"Model {model} may be deprecated or unsupported",
                    details={"available_models": PERPLEXITY_MODELS},
                )

            # Test web search functionality
            response = await asyncio.to_thread(
                lambda: perplexity_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Health check for web search"},
                        {"role": "user", "content": "What is the current date?"},
                    ],
                    max_tokens=50,  # Minimal response
                    temperature=0.1,  # Low temperature for consistent results
                )
            )

            response_time_ms = (time.time() - start_time) * 1000

            if not response or not response.choices or not response.choices[0].message.content:
                return HealthCheckResult(
                    service="perplexity",
                    status="unhealthy",
                    response_time_ms=response_time_ms,
                    timestamp=datetime.now(timezone.utc),
                    error="Invalid response structure from Perplexity API",
                )

            # Check for web search indicators (URLs, citations)
            response_content = response.choices[0].message.content
            has_web_indicators = any(
                [
                    "http" in response_content.lower(),
                    "[" in response_content and "]" in response_content,
                    "source" in response_content.lower(),
                ]
            )

            status = "healthy"
            if response_time_ms > 8000:  # 8 seconds (web search takes longer)
                status = "degraded"
            elif response_time_ms > 15000:  # 15 seconds
                status = "unhealthy"

            return HealthCheckResult(
                service="perplexity",
                status=status,
                response_time_ms=response_time_ms,
                timestamp=datetime.now(timezone.utc),
                details={
                    "model": model,
                    "response_length": len(response_content),
                    "has_web_indicators": has_web_indicators,
                    "usage": (
                        getattr(response, "usage", {}).__dict__
                        if hasattr(response, "usage")
                        else {}
                    ),
                },
            )

        except Exception as e:  # noqa: BLE001
            response_time_ms = (time.time() - start_time) * 1000
            error_details = classify_error(e)

            return HealthCheckResult(
                service="perplexity",
                status="unhealthy",
                response_time_ms=response_time_ms,
                timestamp=datetime.now(timezone.utc),
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
                    timestamp=datetime.now(timezone.utc),
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
            if latency_ms and latency_ms > 500:  # 500ms latency
                status = "degraded"
            elif latency_ms and latency_ms > 1000:  # 1 second latency
                status = "unhealthy"

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
                timestamp=datetime.now(timezone.utc),
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
                timestamp=datetime.now(timezone.utc),
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
        self, clients: dict[str, Any], config: dict[str, Any]
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
                    clients["perplexity"], config
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

    def get_health_summary(self) -> dict[str, Any]:
        """Get comprehensive health summary for all services."""
        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": {},
            "overall_status": "healthy",
        }

        unhealthy_count = 0
        degraded_count = 0

        for service, metrics in self.metrics.items():
            service_summary = {
                "status": self._determine_service_status(metrics),
                "uptime_percentage": round(metrics.uptime_percentage, 2),
                "average_response_time_ms": round(metrics.average_response_time_ms, 2),
                "total_checks": metrics.total_checks,
                "consecutive_failures": metrics.consecutive_failures,
                "last_check": (
                    metrics.last_check_time.isoformat() if metrics.last_check_time else None
                ),
                "last_success": (
                    metrics.last_success_time.isoformat() if metrics.last_success_time else None
                ),
            }

            summary["services"][service] = service_summary

            if service_summary["status"] == "unhealthy":
                unhealthy_count += 1
            elif service_summary["status"] == "degraded":
                degraded_count += 1

        # Determine overall status
        if unhealthy_count > 0:
            summary["overall_status"] = "unhealthy"
        elif degraded_count > 0:
            summary["overall_status"] = "degraded"

        return summary

    def _determine_service_status(self, metrics: APIHealthMetrics) -> str:
        """Determine service status based on metrics."""
        if metrics.consecutive_failures >= 3:
            return "unhealthy"
        if metrics.consecutive_failures > 0 or metrics.uptime_percentage < 90:
            return "degraded"
        return "healthy"

    async def start_monitoring(self, clients: dict[str, Any], config: dict[str, Any]):
        """Start background health monitoring."""
        if self._monitoring_active:
            return

        self._monitoring_active = True
        self.logger.info("Starting API health monitoring")

        async def _monitor_tick() -> None:
            results = await self.run_all_health_checks(clients, config)

            # Log critical issues
            for service, result in results.items():
                if result.status == "unhealthy":
                    self.logger.error(f"Service {service} is unhealthy: {result.error}")
                elif result.status == "degraded":
                    self.logger.warning(
                        f"Service {service} is degraded: response time "
                        f"{result.response_time_ms:.1f}ms"
                    )

        async def monitor_loop():
            while self._monitoring_active:
                try:
                    await _monitor_tick()
                except Exception:  # noqa: PERF203
                    self.logger.exception("Error in health monitoring loop")
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(self.check_interval)

        self._monitor_task = asyncio.create_task(monitor_loop())

    async def stop_monitoring(self):
        """Stop background health monitoring."""
        if not self._monitoring_active:
            return

        self._monitoring_active = False
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task

        self.logger.info("Stopped API health monitoring")


def validate_api_configuration(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Validate API configuration against current specifications.

    Returns:
        Tuple of (warnings, errors) lists
    """
    return validate_full_config(config)


# Global health monitor instance
health_monitor = APIHealthMonitor()


async def run_startup_health_checks(clients: dict[str, Any], config: dict[str, Any]) -> bool:
    """Run health checks during application startup.

    Returns:
        bool: True if all critical services are healthy
    """
    logger = logging.getLogger(__name__)
    logger.info("Running startup health checks...")

    try:
        results = await health_monitor.run_all_health_checks(clients, config)

        critical_services_healthy = True

        for service, result in results.items():
            if result.status == "unhealthy":
                logger.error(f"STARTUP: {service} service is unhealthy: {result.error}")
                critical_services_healthy = False
            elif result.status == "degraded":
                logger.warning(
                    f"STARTUP: {service} service is degraded "
                    f"(response time: {result.response_time_ms:.1f}ms)"
                )
            else:
                logger.info(
                    f"STARTUP: {service} service is healthy "
                    f"(response time: {result.response_time_ms:.1f}ms)"
                )

    except Exception:
        logger.exception("Failed to run startup health checks")
        return False
    else:
        return critical_services_healthy
