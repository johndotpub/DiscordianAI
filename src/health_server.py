"""HTTP health endpoint for DiscordianAI.

Provides liveness and readiness probes compatible with Kubernetes,
Docker, and load balancer health checks via a lightweight Starlette
ASGI server.

Routes:
    GET /health       - Full health summary (bot + API + pool metrics)
    GET /health/live   - Liveness probe (always 200 if process is alive)
    GET /health/ready  - Readiness probe (200 only when bot can serve requests)
"""

import asyncio
import contextlib
import logging
import math
import time
from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from .error_handling import get_circuit_breaker_states

DEFAULT_HEALTH_HOST = "127.0.0.1"
DEFAULT_HEALTH_PORT = 8080
DEFAULT_PROVIDER_STALE_SECONDS = 300.0
PROVIDER_NAMES = ("openai", "perplexity")
WALL_CLOCK_EPOCH_SECONDS = 1_000_000_000

logger = logging.getLogger(__name__)


async def _health_handler(request: Any) -> JSONResponse:
    """Return full health summary including bot, API, and pool status."""
    app = request.app
    health_data = await _collect_health_data(app)
    status_code = 200 if health_data.get("status") == "healthy" else 503
    return JSONResponse(health_data, status_code=status_code)


async def _liveness_handler(_request: Any) -> JSONResponse:
    """Liveness probe - returns 200 as long as the process is alive."""
    return JSONResponse({"status": "alive"})


async def _readiness_handler(request: Any) -> JSONResponse:
    """Readiness probe - returns 200 only when the bot can serve requests."""
    app = request.app
    bot = app.state.deps.get("bot")
    client = app.state.deps.get("client")
    perplexity_client = app.state.deps.get("perplexity_client")
    health_data = await _collect_health_data(app)

    has_api_client = client is not None or perplexity_client is not None
    ready = (
        bot is not None
        and bot.is_ready()
        and has_api_client
        and health_data.get("status") == "healthy"
    )

    if ready:
        return JSONResponse({"status": "ready"})

    return JSONResponse(
        {
            "status": "not_ready",
            "health_status": health_data.get("status"),
            "failing_providers": health_data.get("failing_providers", []),
            "providers": health_data.get("providers", {}),
        },
        status_code=503,
    )


def _collect_breaker_states(deps: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return breaker snapshots, preferring the instances wired into deps."""
    states = get_circuit_breaker_states()
    wired = deps.get("circuit_breakers")
    if isinstance(wired, dict):
        for provider, breaker in wired.items():
            if hasattr(breaker, "snapshot"):
                states[provider] = breaker.snapshot()
            elif isinstance(breaker, dict):
                states[provider] = dict(breaker)
    return states


def _provider_stale_after(config: dict[str, Any]) -> float:
    """Return the age after which a provider's last success is reported as stale."""
    raw_value = config.get("HEALTH_PROVIDER_STALE_SECONDS", DEFAULT_PROVIDER_STALE_SECONDS)
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_PROVIDER_STALE_SECONDS
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_PROVIDER_STALE_SECONDS
    return value


def _finite_number(value: Any, default: float = 0.0) -> float:
    """Coerce a value to a finite float, falling back to a default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _timestamp_age(timestamp: float, monotonic_now: float) -> float | None:
    """Return age for monotonic or wall-clock timestamps.

    A zero timestamp means the event has never happened. Negative values are
    real monotonic readings from before boot on a young clock, so they still
    have a positive age and must not be confused with "never".
    """
    if timestamp == 0:
        return None
    if timestamp <= monotonic_now:
        return max(0.0, monotonic_now - timestamp)
    if timestamp > WALL_CLOCK_EPOCH_SECONDS:
        return max(0.0, time.time() - timestamp)
    return 0.0


def _provider_health(
    deps: dict[str, Any],
    breaker_states: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Describe each provider using observed breaker behaviour."""
    clients = {
        "openai": deps.get("client"),
        "perplexity": deps.get("perplexity_client"),
    }
    stale_after = _provider_stale_after(config)
    now = time.monotonic()
    providers: dict[str, dict[str, Any]] = {}

    for provider in PROVIDER_NAMES:
        snapshot = breaker_states.get(provider, {})
        configured = clients[provider] is not None
        state = str(snapshot.get("state") or "CLOSED").upper()
        failures = max(
            0,
            int(
                _finite_number(
                    snapshot.get("consecutive_failures", snapshot.get("failure_count", 0))
                )
            ),
        )
        last_failure_time = _finite_number(snapshot.get("last_failure_time", 0.0))
        last_success_time = _finite_number(snapshot.get("last_success_time", 0.0))
        success_age = _timestamp_age(last_success_time, now)

        if not configured:
            status = "not_configured"
        elif state == "OPEN":
            status = "unhealthy"
        elif state == "HALF_OPEN" or (failures > 0 and last_failure_time > last_success_time):
            status = "degraded"
        else:
            status = "healthy"

        providers[provider] = {
            "configured": configured,
            "state": state,
            "status": status,
            "healthy": status == "healthy",
            "consecutive_failures": failures,
            "failure_count": failures,
            "last_failure_time": last_failure_time,
            "last_success_time": last_success_time,
            "last_success_age_seconds": (
                round(success_age, 1) if success_age is not None else None
            ),
            "last_success_stale": success_age is not None and success_age > stale_after,
        }

    return providers


def _safe_latency_ms(bot: Any) -> float | None:
    """Return a finite, positive Discord latency in milliseconds."""
    latency = _finite_number(getattr(bot, "latency", 0.0))
    if latency <= 0:
        return None
    return round(latency * 1000, 1)


def _sanitize_json(value: Any) -> Any:
    """Replace non-finite floats so the response always renders as JSON."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json(item) for item in value]
    return value


async def _collect_health_data(app: Starlette) -> dict[str, Any]:
    """Gather health information from all subsystems."""
    bot = app.state.deps.get("bot")
    config = app.state.deps.get("config", {})

    services: dict[str, Any] = {}
    overall = "healthy"

    openai_client = app.state.deps.get("client")
    perplexity_client = app.state.deps.get("perplexity_client")

    services["openai"] = "configured" if openai_client else "not_configured"
    services["perplexity"] = "configured" if perplexity_client else "not_configured"
    services["openai_configured"] = openai_client is not None
    services["perplexity_configured"] = perplexity_client is not None

    if bot and bot.is_ready():
        services["discord"] = "connected"
        services["guilds"] = len(bot.guilds)
        services["latency_ms"] = _safe_latency_ms(bot)
    else:
        services["discord"] = "disconnected"
        overall = "unhealthy"

    pool_manager = app.state.deps.get("connection_pool_manager")
    if pool_manager and hasattr(pool_manager, "get_pool_metrics"):
        services["pool"] = pool_manager.get_pool_metrics()
    elif pool_manager and hasattr(pool_manager, "check_pool_health"):
        services["pool"] = pool_manager.check_pool_health()

    if not openai_client and not perplexity_client:
        overall = "unhealthy"

    breaker_states = _collect_breaker_states(app.state.deps)
    provider_health = _provider_health(app.state.deps, breaker_states, config)
    failing_providers = [
        provider
        for provider, details in provider_health.items()
        if details["status"] in {"degraded", "unhealthy"}
    ]

    if any(details["status"] == "unhealthy" for details in provider_health.values()):
        overall = "unhealthy"
    elif (
        any(details["status"] == "degraded" for details in provider_health.values())
        and overall == "healthy"
    ):
        overall = "degraded"

    services["circuit_breakers"] = breaker_states
    services["providers"] = provider_health
    services["provider_health"] = provider_health
    services["failing_providers"] = failing_providers

    return _sanitize_json(
        {
            "status": overall,
            "mode": _detect_mode(config),
            "model": config.get("GPT_MODEL", "unknown"),
            "perplexity_model": config.get("PERPLEXITY_MODEL", "unknown"),
            "services": services,
            "circuit_breakers": breaker_states,
            "providers": provider_health,
            "provider_health": provider_health,
            "failing_providers": failing_providers,
        }
    )


def _detect_mode(config: dict[str, Any]) -> str:
    """Determine the operation mode from config."""
    has_openai = bool(config.get("OPENAI_API_KEY"))
    has_perplexity = bool(config.get("PERPLEXITY_API_KEY"))
    if has_openai and has_perplexity:
        return "hybrid"
    if has_openai:
        return "openai_only"
    if has_perplexity:
        return "perplexity_only"
    return "none"


def create_health_app(deps: dict[str, Any]) -> Starlette:
    """Create a Starlette application with health check routes.

    Args:
        deps: The bot dependency container.

    Returns:
        Starlette: Configured ASGI application.
    """
    app = Starlette(
        routes=[
            Route("/health", _health_handler),
            Route("/health/live", _liveness_handler),
            Route("/health/ready", _readiness_handler),
        ],
    )
    app.state.deps = deps
    return app


class HealthServer:
    """Manages the lifecycle of the health check HTTP server.

    Runs as a lightweight ASGI server alongside the Discord bot.
    Binds to 127.0.0.1 by default (not externally accessible).
    """

    def __init__(
        self,
        deps: dict[str, Any],
        host: str = DEFAULT_HEALTH_HOST,
        port: int = DEFAULT_HEALTH_PORT,
    ) -> None:
        """Initialize health server with deps and network config."""
        self._deps = deps
        self._host = host
        self._port = port
        self._app = create_health_app(deps)
        self._server: Any | None = None
        self._task: asyncio.Task | None = None
        self._disabled_reason: str | None = None

    def _disable(self, reason: str) -> None:
        """Disable the endpoint once and record why."""
        if self._disabled_reason is not None:
            return
        self._disabled_reason = reason
        self._server = None
        self._task = None
        logger.error("health server disabled: %s", reason)

    async def start(self) -> None:
        """Start the health server, disabling it safely if it cannot bind."""
        if self._task and not self._task.done():
            logger.debug("Health server already running")
            return
        if self._disabled_reason is not None:
            logger.debug("Health server remains disabled: %s", self._disabled_reason)
            return
        await self._start_server()

    async def _start_server(self) -> None:
        """Create, start, and own the configured uvicorn server."""
        config = self._deps.get("config", {})
        enabled = config.get("HEALTH_ENABLED", True)
        if isinstance(enabled, str):
            enabled = str(enabled).lower() in ("true", "1", "yes")
        else:
            enabled = bool(enabled)

        if not enabled:
            logger.info("Health server disabled by configuration")
            return

        try:
            import uvicorn  # noqa: PLC0415 — lazy import; only needed when start() is called
        except ImportError:
            self._disable("uvicorn is not installed")
            return

        logger.info("Health server starting on %s:%s", self._host, self._port)
        server = uvicorn.Server(
            uvicorn.Config(
                self._app,
                host=self._host,
                port=self._port,
                log_level="warning",
                access_log=False,
            )
        )
        self._server = server

        try:
            if isinstance(server.config, uvicorn.Config):
                load_result = server.config.load()
                if asyncio.iscoroutine(load_result):
                    await load_result
                server.lifespan = server.config.lifespan_class(server.config)
            await server.startup()
        except SystemExit as exc:
            self._disable(f"uvicorn startup exited with status {exc.code}")
            return
        except OSError as exc:
            self._disable(str(exc) or type(exc).__name__)
            return
        except Exception as exc:  # noqa: BLE001 — a failed endpoint must not stop the bot
            self._disable(str(exc) or type(exc).__name__)
            return

        if not getattr(server, "started", False):
            self._disable("uvicorn did not report a started server")
            return

        self._task = asyncio.create_task(self._run_server(server))

    async def _run_server(self, server: Any) -> None:
        """Run the server loop and always shut the owned server down."""
        try:
            if not server.should_exit:
                await server.main_loop()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Health server stopped unexpectedly")
        finally:
            if getattr(server, "started", False):
                try:
                    await server.shutdown()
                except Exception:
                    logger.exception("Health server shutdown failed")

    async def stop(self) -> None:
        """Stop the health server."""
        task = self._task
        server = self._server
        if server is not None:
            server.should_exit = True

        if task is not None:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, SystemExit):
                await task
            logger.info("Health server stopped")

        self._task = None
        self._server = None
