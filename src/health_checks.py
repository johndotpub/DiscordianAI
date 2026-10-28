"""API health check and monitoring system for DiscordianAI.

This module provides:
- Health checks for OpenAI, Perplexity, and Discord APIs
- Parameter validation against current API specifications
- Health status reporting and metrics collection
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial, partialmethod
import logging
import time
from typing import Any

from .config import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PERPLEXITY_MODEL,
    OPENAI_VALID_MODELS,
    PERPLEXITY_MODELS,
    is_supported_openai_model,
)
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


@dataclass(frozen=True)
class ProviderHealthSpec:
    """Describe one service's health-check inputs and thresholds."""

    service: str
    display_name: str
    client_key: str
    model_key: str | None = None
    default_model: str | None = None
    allowed_models: tuple[str, ...] = ()
    model_validator: Callable[[str | None], bool] | None = None
    degraded_threshold_ms: float = 0.0
    unhealthy_threshold_ms: float = 0.0
    deprecated_model_limit: int | None = None
    kind: str = "api"


PROVIDER_HEALTH_SPECS: dict[str, ProviderHealthSpec] = {
    "openai": ProviderHealthSpec(
        service="openai",
        display_name="OpenAI",
        client_key="openai",
        model_key="GPT_MODEL",
        default_model=DEFAULT_OPENAI_MODEL,
        allowed_models=tuple(OPENAI_VALID_MODELS),
        model_validator=is_supported_openai_model,
        degraded_threshold_ms=OPENAI_RESPONSE_DEGRADED_THRESHOLD_MS,
        unhealthy_threshold_ms=OPENAI_RESPONSE_UNHEALTHY_THRESHOLD_MS,
        deprecated_model_limit=5,
    ),
    "perplexity": ProviderHealthSpec(
        service="perplexity",
        display_name="Perplexity",
        client_key="perplexity",
        model_key="PERPLEXITY_MODEL",
        default_model=DEFAULT_PERPLEXITY_MODEL,
        allowed_models=tuple(PERPLEXITY_MODELS),
        degraded_threshold_ms=PERPLEXITY_RESPONSE_DEGRADED_THRESHOLD_MS,
        unhealthy_threshold_ms=PERPLEXITY_RESPONSE_UNHEALTHY_THRESHOLD_MS,
    ),
    "discord": ProviderHealthSpec(
        service="discord",
        display_name="Discord",
        client_key="discord",
        degraded_threshold_ms=DISCORD_LATENCY_DEGRADED_THRESHOLD_MS,
        unhealthy_threshold_ms=DISCORD_LATENCY_UNHEALTHY_THRESHOLD_MS,
        kind="latency",
    ),
}


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

    @staticmethod
    def _model_is_supported(spec: ProviderHealthSpec, model: str | None) -> bool:
        if spec.model_validator is not None:
            return spec.model_validator(model)
        return model in spec.allowed_models

    @staticmethod
    def _classify_status(
        elapsed_ms: float | None,
        spec: ProviderHealthSpec,
    ) -> str:
        if elapsed_ms is None:
            return "healthy"
        if elapsed_ms > spec.unhealthy_threshold_ms:
            return "unhealthy"
        if elapsed_ms > spec.degraded_threshold_ms:
            return "degraded"
        return "healthy"

    def _exception_result(
        self,
        service: str,
        start_time: float,
        error: Exception,
    ) -> HealthCheckResult:
        response_time_ms = (time.time() - start_time) * 1000
        error_details = classify_error(error)

        return HealthCheckResult(
            service=service,
            status="unhealthy",
            response_time_ms=response_time_ms,
            timestamp=datetime.now(UTC),
            error=str(error),
            details={
                "error_type": error_details.error_type.value,
                "error_severity": error_details.severity.value,
            },
        )

    async def _check_api_health(
        self,
        spec: ProviderHealthSpec,
        client: Any,
        config: dict[str, Any],
    ) -> HealthCheckResult:
        start_time = time.time()

        try:
            model = config.get(spec.model_key, spec.default_model)

            if not self._model_is_supported(spec, model):
                limit = spec.deprecated_model_limit
                available_models = list(
                    spec.allowed_models[:limit] if limit is not None else spec.allowed_models
                )
                return HealthCheckResult(
                    service=spec.service,
                    status="degraded",
                    response_time_ms=0,
                    timestamp=datetime.now(UTC),
                    error=f"Model {model} may be deprecated or unsupported",
                    details={"available_models": available_models},
                )

            response = await client.models.list()

            response_time_ms = (time.time() - start_time) * 1000

            model_ids = [
                model_id
                for item in getattr(response, "data", [])
                if (model_id := getattr(item, "id", None))
            ]
            if not model_ids:
                return HealthCheckResult(
                    service=spec.service,
                    status="unhealthy",
                    response_time_ms=response_time_ms,
                    timestamp=datetime.now(UTC),
                    error=f"Invalid response structure from {spec.display_name} model listing API",
                )

            status = self._classify_status(response_time_ms, spec)

            return HealthCheckResult(
                service=spec.service,
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
            return self._exception_result(spec.service, start_time, e)

    async def _check_latency_health(
        self,
        spec: ProviderHealthSpec,
        bot_client: Any,
    ) -> HealthCheckResult:
        start_time = time.time()

        try:
            if not bot_client.is_ready():
                return HealthCheckResult(
                    service=spec.service,
                    status="unhealthy",
                    response_time_ms=0,
                    timestamp=datetime.now(UTC),
                    error="Discord bot is not ready/connected",
                )

            response_time_ms = (time.time() - start_time) * 1000

            latency_ms = (
                getattr(bot_client, "latency", 0) * 1000
                if hasattr(bot_client, "latency")
                else None
            )

            status = self._classify_status(latency_ms, spec)

            guild_count = len(bot_client.guilds) if hasattr(bot_client, "guilds") else 0
            user_count = (
                sum(guild.member_count for guild in bot_client.guilds if guild.member_count)
                if hasattr(bot_client, "guilds")
                else 0
            )

            return HealthCheckResult(
                service=spec.service,
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
            return self._exception_result(spec.service, start_time, e)

    async def check_provider_health(
        self,
        service: str,
        client: Any,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        """Run the table-described health check for one service."""
        spec = PROVIDER_HEALTH_SPECS[service]
        if spec.kind == "latency":
            return await self._check_latency_health(spec, client)
        return await self._check_api_health(spec, client, config or {})

    check_openai_health = partialmethod(check_provider_health, "openai")
    check_perplexity_health = partialmethod(check_provider_health, "perplexity")
    check_discord_health = partialmethod(check_provider_health, "discord")

    def __getattr__(self, name: str) -> Any:
        """Resolve ``check_<service>_health`` names from the provider table."""
        if name.startswith("check_") and name.endswith("_health"):
            service = name[len("check_") : -len("_health")]
            if service in PROVIDER_HEALTH_SPECS:
                return partial(self.check_provider_health, service)
        message = f"{type(self).__name__!r} object has no attribute {name!r}"
        raise AttributeError(message)

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
        results: dict[str, HealthCheckResult] = {}

        for service, spec in PROVIDER_HEALTH_SPECS.items():
            client = clients.get(spec.client_key)
            if not client:
                continue
            try:
                checker = getattr(self, f"check_{service}_health")
                result = await checker(client, config)
                results[service] = result
                self.record_health_check(result)
            except Exception:
                self.logger.exception("Failed to check %s health", spec.display_name)

        return results
