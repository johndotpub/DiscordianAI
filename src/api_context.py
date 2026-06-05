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

from .error_handling import (
    DEFAULT_API_RETRY_CONFIG,
    RetryConfig,
    classify_error,
    error_tracker,
    retry_with_backoff,
)
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


async def call_with_retry(  # noqa: PLR0913
    coro_factory: Any,
    service: str,
    logger: logging.Logger,
    *,
    max_attempts: int = 2,
    base_delay: float = 4.0,
    max_delay: float = 4.0,
    request: AIRequest | None = None,
) -> APICallResult:
    """Execute an API call with retry and comprehensive lifecycle tracking.

    This is a convenience function that combines ``api_call`` context manager
    with ``retry_with_backoff`` for callers that want retry support without
    managing the context manager manually.

    Args:
        coro_factory: An async callable (zero-arg) that performs the API call.
        service: Service name for logging/tracking.
        logger: Logger instance.
        max_attempts: Maximum number of retry attempts.
        base_delay: Base delay for exponential backoff.
        max_delay: Maximum delay between retries.
        request: Optional ``AIRequest`` for user-level context.

    Returns:
        ``APICallResult`` with outcome details.
    """
    retry_config = (
        DEFAULT_API_RETRY_CONFIG
        if (
            max_attempts == DEFAULT_API_RETRY_CONFIG.max_attempts
            and base_delay == DEFAULT_API_RETRY_CONFIG.base_delay
            and max_delay == DEFAULT_API_RETRY_CONFIG.max_delay
        )
        else RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            exponential_base=1.0,
            jitter=True,
        )
    )

    start_time = time.monotonic()
    api_result = APICallResult(service=service)

    try:
        async with api_call(service, logger, request) as ctx:
            response = await retry_with_backoff(coro_factory, retry_config, logger)
            ctx.set_result(response)
            api_result.value = response
            api_result.success = True
    except Exception as exc:  # noqa: BLE001
        api_result.error = exc
        api_result.success = False

    api_result.elapsed_seconds = time.monotonic() - start_time
    return api_result


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
