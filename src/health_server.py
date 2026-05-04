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
from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

DEFAULT_HEALTH_HOST = "127.0.0.1"
DEFAULT_HEALTH_PORT = 8080

logger = logging.getLogger(__name__)


async def _health_handler(request: Any) -> JSONResponse:
    """Return full health summary including bot, API, and pool status."""
    app = request.app
    health_data = await _collect_health_data(app)
    status_code = 200 if health_data.get("status") != "unhealthy" else 503
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

    has_api_client = client is not None or perplexity_client is not None
    ready = bot is not None and bot.is_ready() and has_api_client

    if ready:
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "not_ready"}, status_code=503)


async def _collect_health_data(app: Starlette) -> dict[str, Any]:
    """Gather health information from all subsystems."""
    bot = app.state.deps.get("bot")
    config = app.state.deps.get("config", {})

    services: dict[str, Any] = {}
    overall = "healthy"

    openai_client = app.state.deps.get("client")
    perplexity_client = app.state.deps.get("perplexity_client")

    services["openai"] = "configured" if openai_client else "not_configured"
    services["perplexity"] = (
        "configured" if perplexity_client else "not_configured"
    )

    if bot and bot.is_ready():
        services["discord"] = "connected"
        services["guilds"] = len(bot.guilds)
        services["latency_ms"] = round(bot.latency * 1000, 1)
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

    return {
        "status": overall,
        "mode": _detect_mode(config),
        "model": config.get("GPT_MODEL", "unknown"),
        "perplexity_model": config.get("PERPLEXITY_MODEL", "unknown"),
        "services": services,
    }


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
        self._server = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the health server as an asyncio task."""
        if self._task and not self._task.done():
            logger.debug("health_server: already running")
            return

        config = self._deps.get("config", {})
        enabled = config.get("HEALTH_ENABLED", True)
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("true", "1", "yes")

        if not enabled:
            logger.info("health_server: disabled by configuration")
            return

        import uvicorn  # noqa: PLC0415 — lazy import; only needed when start() is called

        logger.info(
            "health_server: starting on %s:%s", self._host, self._port
        )
        self._task = asyncio.create_task(
            uvicorn.Server(
                uvicorn.Config(
                    self._app,
                    host=self._host,
                    port=self._port,
                    log_level="warning",
                    access_log=False,
                ),
            ).serve(),
        )

    async def stop(self) -> None:
        """Stop the health server."""
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            logger.info("health_server: stopped")
