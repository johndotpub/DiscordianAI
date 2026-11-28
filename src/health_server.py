"""HTTP health endpoint for DiscordianAI.

Provides liveness and readiness probes compatible with Kubernetes,
Docker, and load balancer health checks via a lightweight aiohttp
server.

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

from aiohttp import web

from .config import (
    DEFAULT_HEALTH_HOST,
    DEFAULT_HEALTH_PORT,
    DEFAULT_HEALTH_PROVIDER_STALE_SECONDS,
)
from .error_handling import get_circuit_breaker_states, get_circuit_breaker_timeout
from .providers.registry import client_deps_key, provider_names

DEFAULT_PROVIDER_STALE_SECONDS = float(DEFAULT_HEALTH_PROVIDER_STALE_SECONDS)
PROVIDER_NAMES = provider_names()
WALL_CLOCK_EPOCH_SECONDS = 1_000_000_000

logger = logging.getLogger(__name__)
_DEPS_KEY = web.AppKey("deps", dict)


async def _health_handler(request: web.Request) -> web.Response:
    """Return full health summary including bot, API, and pool status."""
    health_data = await _collect_health_data(request.app[_DEPS_KEY])
    status_code = 200 if health_data.get("status") == "healthy" else 503
    return web.json_response(health_data, status=status_code)


async def _liveness_handler(_request: web.Request) -> web.Response:
    """Liveness probe - returns 200 as long as the process is alive."""
    return web.json_response({"status": "alive"})


async def _readiness_handler(request: web.Request) -> web.Response:
    """Readiness probe - returns 200 only when the bot can serve requests."""
    deps = request.app[_DEPS_KEY]
    bot = deps.get("bot")
    health_data = await _collect_health_data(deps)

    has_api_client = any(deps.get(client_deps_key(name)) is not None for name in PROVIDER_NAMES)
    ready = _bot_connected(bot) and has_api_client and health_data.get("status") == "healthy"

    if ready:
        return web.json_response({"status": "ready"})

    return web.json_response(
        {
            "status": "not_ready",
            "health_status": health_data.get("status"),
            "failing_providers": health_data.get("failing_providers", []),
            "providers": health_data.get("providers", {}),
        },
        status=503,
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


def _breaker_timeout(deps: dict[str, Any], provider: str) -> float:
    """Return the recovery timeout for a provider's wired or shared breaker."""
    wired = deps.get("circuit_breakers")
    if isinstance(wired, dict):
        breaker = wired.get(provider)
        timeout = getattr(breaker, "timeout", None)
        if timeout is not None:
            return _finite_number(timeout, get_circuit_breaker_timeout(provider))
    return get_circuit_breaker_timeout(provider)


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
    clients = {name: deps.get(client_deps_key(name)) for name in PROVIDER_NAMES}
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
        failure_age = _timestamp_age(last_failure_time, now)
        recovering = failure_age is not None and failure_age > _breaker_timeout(deps, provider)

        if not configured:
            status = "not_configured"
        elif state == "OPEN":
            # The breaker's next call would be admitted as a HALF_OPEN probe.
            # The health vocabulary has no separate "recovering" status, so an
            # OPEN breaker past its timeout is reported healthy; within the
            # timeout it is still unhealthy.
            status = "healthy" if recovering else "unhealthy"
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


def _bot_connected(bot: Any) -> bool:
    """Return the live gateway state, not just discord.py's sticky ``is_ready``.

    ``Client.is_ready()`` stays true across a gateway disconnect. The bot
    manager records each disconnect and resume on the client itself, so the
    health endpoint can report an outage that discord.py has not cleared.
    """
    if bot is None:
        return False
    ready = bool(bot.is_ready())
    gateway_state = getattr(bot, "discordian_gateway_connected", None)
    if isinstance(gateway_state, bool):
        return gateway_state and ready
    return ready


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


async def _collect_health_data(deps: dict[str, Any]) -> dict[str, Any]:
    """Gather health information from all subsystems."""
    bot = deps.get("bot")
    config = deps.get("config", {})

    services: dict[str, Any] = {}
    overall = "healthy"

    openai_client = deps.get("client")
    perplexity_client = deps.get("perplexity_client")

    services["openai"] = "configured" if openai_client else "not_configured"
    services["perplexity"] = "configured" if perplexity_client else "not_configured"
    services["openai_configured"] = openai_client is not None
    services["perplexity_configured"] = perplexity_client is not None

    if _bot_connected(bot):
        services["discord"] = "connected"
        services["guilds"] = len(bot.guilds)
        services["latency_ms"] = _safe_latency_ms(bot)
    else:
        services["discord"] = "disconnected"
        overall = "unhealthy"

    pool_manager = deps.get("connection_pool_manager")
    if pool_manager and hasattr(pool_manager, "get_pool_metrics"):
        services["pool"] = pool_manager.get_pool_metrics()
    elif pool_manager and hasattr(pool_manager, "check_pool_health"):
        services["pool"] = pool_manager.check_pool_health()

    if not openai_client and not perplexity_client:
        overall = "unhealthy"

    breaker_states = _collect_breaker_states(deps)
    provider_health = _provider_health(deps, breaker_states, config)
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


def create_health_app(deps: dict[str, Any]) -> web.Application:
    """Create an aiohttp application with health check routes.

    Args:
        deps: The bot dependency container.

    Returns:
        aiohttp.web.Application: Configured web application.
    """
    app = web.Application()
    app[_DEPS_KEY] = deps
    routes = (
        ("/health", _health_handler),
        ("/health/live", _liveness_handler),
        ("/health/ready", _readiness_handler),
    )
    for route, handler in routes:
        app.router.add_get(route, handler)
        # Probes that use a trailing slash keep the same status and body.
        app.router.add_get(f"{route}/", handler)
    return app


class HealthServer:
    """Manages the lifecycle of the health check HTTP server.

    Runs as a lightweight aiohttp server alongside the Discord bot.
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
        self._server: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._cleanup_done = False
        self._disabled_reason: str | None = None

    def _disable(self, reason: str) -> None:
        """Disable the endpoint once and record why."""
        if self._disabled_reason is not None:
            return
        self._disabled_reason = reason
        self._server = None
        self._site = None
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
        """Create, start, and own the configured aiohttp server."""
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
            import aiohttp  # noqa: PLC0415 — lazy import; only needed when start() is called
        except ImportError:
            self._disable("aiohttp is not installed")
            return

        logger.info("Health server starting on %s:%s", self._host, self._port)
        self._stop_event = asyncio.Event()
        self._cleanup_done = False
        runner = aiohttp.web.AppRunner(self._app, access_log=None)
        self._server = runner

        try:
            await runner.setup()
            site = aiohttp.web.TCPSite(runner, self._host, self._port)
            await site.start()
        except SystemExit as exc:
            await self._cleanup_failed_start(runner)
            self._disable(f"aiohttp startup exited with status {exc.code}")
            return
        except OSError as exc:
            await self._cleanup_failed_start(runner)
            self._disable(str(exc) or type(exc).__name__)
            return
        except Exception as exc:  # noqa: BLE001 — a failed endpoint must not stop the bot
            await self._cleanup_failed_start(runner)
            self._disable(str(exc) or type(exc).__name__)
            return

        if not runner.addresses:
            await self._cleanup_failed_start(runner)
            self._disable("aiohttp did not report a started server")
            return

        self._site = site
        self._task = asyncio.create_task(self._run_server(runner))

    async def _cleanup_failed_start(self, runner: web.AppRunner) -> None:
        """Release a runner whose startup failed without raising."""
        with contextlib.suppress(Exception):
            await runner.cleanup()

    async def _release_runner(self, runner: web.AppRunner) -> None:
        """Clean up the owned runner once, logging any shutdown failure."""
        if self._cleanup_done:
            return
        self._cleanup_done = True
        try:
            await runner.cleanup()
        except Exception:
            logger.exception("Health server shutdown failed")

    async def _run_server(self, runner: web.AppRunner) -> None:
        """Wait for the stop signal and always clean up the owned runner."""
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Health server stopped unexpectedly")
        finally:
            await self._release_runner(runner)

    async def stop(self) -> None:
        """Stop the health server."""
        task = self._task
        runner = self._server
        self._stop_event.set()

        if task is not None:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, SystemExit):
                await task
            logger.info("Health server stopped")

        if runner is not None:
            await self._release_runner(runner)

        self._task = None
        self._server = None
        self._site = None
