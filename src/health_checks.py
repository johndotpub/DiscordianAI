"""API health check and monitoring system for DiscordianAI.

This module provides startup reachability checks for the configured providers
and Discord. API providers are checked through their adapter ``probe()``, which
bounds the model listing call; /health itself reports observed breaker state.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial, partialmethod
import logging
import time
from typing import Any

from .connection_pool import versioned_perplexity_client
from .error_handling import classify_error
from .providers.base import ProbeResult
from .providers.registry import PROVIDERS

# Health check thresholds
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
    versioned_client: bool = False
    kind: str = "api"
    probe: Callable[[Any], Awaitable[ProbeResult]] | None = None


def _provider_health_specs() -> dict[str, ProviderHealthSpec]:
    """Build AI provider specs from the registry and append Discord."""
    specs: dict[str, ProviderHealthSpec] = {}
    for name, spec in PROVIDERS.items():
        if not spec.health:
            continue
        specs[name] = ProviderHealthSpec(
            service=name,
            display_name=spec.label,
            client_key=name,
            model_key=spec.model_key,
            probe=lambda client, build=spec.build_adapter: build(client).probe(),
            **spec.health_metadata,
        )
    specs["discord"] = ProviderHealthSpec(
        service="discord",
        display_name="Discord",
        client_key="discord",
        degraded_threshold_ms=DISCORD_LATENCY_DEGRADED_THRESHOLD_MS,
        unhealthy_threshold_ms=DISCORD_LATENCY_UNHEALTHY_THRESHOLD_MS,
        kind="latency",
    )
    return specs


PROVIDER_HEALTH_SPECS: dict[str, ProviderHealthSpec] = _provider_health_specs()


class APIHealthMonitor:
    """Startup health checks for external API dependencies."""

    def __init__(self, check_interval: int = 300):  # 5 minutes default
        """Initialize the health monitor."""
        self.check_interval = check_interval
        self.logger = logging.getLogger(__name__)

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

            if spec.probe is None:
                return HealthCheckResult(
                    service=spec.service,
                    status="unhealthy",
                    response_time_ms=(time.time() - start_time) * 1000,
                    timestamp=datetime.now(UTC),
                    error=f"No provider probe is configured for {spec.display_name}",
                )

            model_client = versioned_perplexity_client(client) if spec.versioned_client else client
            probe = await spec.probe(model_client)
            response_time_ms = (time.time() - start_time) * 1000

            if not probe.ok:
                return self._exception_result(
                    spec.service,
                    start_time,
                    RuntimeError(probe.detail),
                )

            return HealthCheckResult(
                service=spec.service,
                status=self._classify_status(response_time_ms, spec),
                response_time_ms=response_time_ms,
                timestamp=datetime.now(UTC),
                details={"model": model, "probe": probe.detail},
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
        # Every current service has an explicit partialmethod above.
        if name.startswith("check_") and name.endswith("_health"):  # pragma: no cover
            service = name[len("check_") : -len("_health")]
            if service in PROVIDER_HEALTH_SPECS:
                return partial(self.check_provider_health, service)
        message = f"{type(self).__name__!r} object has no attribute {name!r}"
        raise AttributeError(message)

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
            start_time = time.time()
            try:
                checker = getattr(self, f"check_{service}_health")
                result = await checker(client, config)
            except Exception as exc:
                result = HealthCheckResult(
                    service=service,
                    status="unhealthy",
                    response_time_ms=(time.time() - start_time) * 1000,
                    timestamp=datetime.now(UTC),
                    details={"error_type": type(exc).__name__},
                    error=f"check raised {type(exc).__name__}",
                )
                self.logger.exception("Failed to check %s health", spec.display_name)
            results[service] = result
            self.logger.info(
                "Startup health check: service=%s status=%s latency_ms=%.1f error_type=%s",
                result.service,
                result.status,
                result.response_time_ms,
                result.details.get("error_type", "none"),
            )

        return results
