"""API call context manager for lifecycle management.

Provides a unified interface for API call setup, teardown, error handling,
and observability. Replaces the ad-hoc try/except/retry patterns scattered
across processing modules with a single, consistent approach.

Usage::

    async with api_call("openai", request.logger) as ctx:
        response = await openai_client.chat.completions.create(**params)
        ctx.set_result(response)
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
import time
from typing import Any

from .error_handling import classify_error, error_tracker
from .models import AIRequest


@dataclass
class APICallResult:
    """Structured result from an API call context."""

    value: Any = None
    error: Exception | None = None
    elapsed_seconds: float = 0.0
    service: str = ""
    success: bool = False


@dataclass
class APICallContext:
    """Mutable context passed to callers inside ``api_call``.

    Callers should invoke ``set_result`` with the raw API response so the
    context manager can record timing, log outcomes, and track errors
    automatically.
    """

    service: str
    logger: logging.Logger
    start_time: float
    result: Any = None

    def set_result(self, value: Any) -> None:
        """Store the API response for post-call bookkeeping."""
        self.result = value


@asynccontextmanager
async def api_call(
    service: str,
    logger: logging.Logger,
    request: AIRequest | None = None,
) -> AsyncGenerator[APICallContext, None]:
    """Async context manager that wraps an external API call with lifecycle hooks.

    Handles:
    - Timing (start/end) with automatic logging
    - Error classification and tracking
    - Consistent log format across services

    Args:
        service: Name of the API service (e.g. ``"openai"``, ``"perplexity"``).
        logger: Logger instance (possibly context-enhanced via logging_adapter).
        request: Optional ``AIRequest`` for user-level context in log lines.

    Yields:
        An ``APICallContext`` whose ``set_result`` should be called on success.
    """
    ctx = APICallContext(service=service, logger=logger, start_time=time.monotonic())
    user_info = f" for user {request.user.id}" if request else ""
    logger.info("api_call: %s request starting%s", service, user_info)

    try:
        yield ctx
    except Exception as exc:
        elapsed = time.monotonic() - ctx.start_time
        error_details = classify_error(exc)
        error_tracker.record_error(
            error_details,
            {
                "service": service,
                "elapsed_seconds": round(elapsed, 3),
                "function": f"{service}_api_call",
            },
        )
        logger.log(
            _severity_to_log_level(error_details.severity),
            "api_call: %s failed after %.3fs — %s (type=%s, severity=%s)",
            service,
            elapsed,
            error_details.message[:200],
            error_details.error_type.value,
            error_details.severity.value,
        )
        raise
    else:
        elapsed = time.monotonic() - ctx.start_time
        if ctx.result is not None:
            logger.info(
                "api_call: %s succeeded in %.3fs%s",
                service,
                elapsed,
                user_info,
            )
        else:
            logger.warning(
                "api_call: %s completed in %.3fs but no result was set%s",
                service,
                elapsed,
                user_info,
            )


def _severity_to_log_level(severity: Any) -> int:
    """Map an ``ErrorSeverity`` enum value to a stdlib logging level."""
    from .error_handling import ErrorSeverity  # noqa: PLC0415

    mapping = {
        ErrorSeverity.LOW: logging.INFO,
        ErrorSeverity.MEDIUM: logging.WARNING,
        ErrorSeverity.HIGH: logging.ERROR,
        ErrorSeverity.CRITICAL: logging.CRITICAL,
    }
    return mapping.get(severity, logging.ERROR)
