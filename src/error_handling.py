"""Enhanced error handling utilities for critical system paths.

This module provides robust error handling patterns including:
- Exponential backoff with jitter
- Circuit breaker pattern
- Graceful degradation
- Centralized error classification
- Enhanced logging and monitoring
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum
import functools
import logging
import math
import re
import secrets
import threading
import time
from typing import Any

import discord
import httpx
import openai

from .config import ERROR_MESSAGES

try:
    import httpx2
except ImportError:  # pragma: no cover
    httpx2 = None


class ErrorSeverity(Enum):
    """Classification of error severity levels."""

    LOW = "low"  # Minor issues, system continues normally
    MEDIUM = "medium"  # Notable issues, some functionality degraded
    HIGH = "high"  # Major issues, significant functionality impacted
    CRITICAL = "critical"  # System-threatening issues, immediate attention needed


class ErrorType(Enum):
    """Classification of error types for better handling."""

    API_RATE_LIMIT = "api_rate_limit"
    API_TIMEOUT = "api_timeout"
    API_AUTH_ERROR = "api_auth_error"
    API_SERVER_ERROR = "api_server_error"
    NETWORK_ERROR = "network_error"
    DISCORD_CONNECTION = "discord_connection"
    CONFIG_ERROR = "config_error"
    VALIDATION_ERROR = "validation_error"
    UNKNOWN = "unknown"


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a request is rejected because the circuit is open."""

    def __init__(self, provider: str, operation: str | None = None):
        """Build a typed fast-fail error for the provider circuit."""
        self.provider = provider
        self.operation = operation
        detail = f" for {operation}" if operation else ""
        super().__init__(f"Circuit breaker OPEN for {provider}{detail}")


@dataclass
class ErrorDetails:
    """Structured error information for better handling and logging."""

    error_type: ErrorType
    severity: ErrorSeverity
    message: str
    user_message: str
    retry_after: int | None = None
    context: dict[str, Any] | None = None


class CircuitBreaker:
    """Circuit breaker pattern implementation to prevent cascade failures.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failing fast, requests immediately return error
    - HALF_OPEN: Testing if service has recovered
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: int = 60,
        expected_exception: type[Exception] = Exception,
        name: str = "provider",
    ):
        """Initialize circuit breaker parameters."""
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.last_success_time = 0.0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._probe_in_flight = False
        self._lock = asyncio.Lock()

    def _should_attempt_reset(self) -> bool:
        elapsed = self._seconds_since_last_failure()
        return elapsed > self.timeout

    def _seconds_since_last_failure(self) -> float:
        if self.last_failure_time == 0:
            return 0

        now_monotonic = time.monotonic()
        if self.last_failure_time > now_monotonic:
            return self.timeout + 1  # force reset on clock jump

        return now_monotonic - self.last_failure_time

    async def _acquire(self, operation: str | None = None) -> None:
        async with self._lock:
            if self.state == "OPEN":
                if not self._should_attempt_reset():
                    raise CircuitBreakerOpenError(self.name, operation)
                self.state = "HALF_OPEN"

            if self.state == "HALF_OPEN":
                if self._probe_in_flight:
                    raise CircuitBreakerOpenError(self.name, operation)
                self._probe_in_flight = True

    async def _record_failure(self) -> None:
        async with self._lock:
            if self.state == "CLOSED" and self._seconds_since_last_failure() > self.timeout:
                self.failure_count = 0
            self.failure_count += 1
            self.last_failure_time = time.monotonic()
            self._probe_in_flight = False

            if self.state == "HALF_OPEN" or self.failure_count >= self.failure_threshold:
                self.state = "OPEN"

    async def _record_success(self) -> None:
        async with self._lock:
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
            self._probe_in_flight = False
            self.last_success_time = time.monotonic()

    async def _release_probe(self) -> None:
        async with self._lock:
            self._probe_in_flight = False

    async def call(self, func, *args, **kwargs):
        """Run one logical operation through the breaker."""
        operation = getattr(func, "__name__", None)
        await self._acquire(operation)

        try:
            result = await func(*args, **kwargs)
        except self.expected_exception:
            await self._record_failure()
            raise
        except BaseException:
            await self._release_probe()
            raise
        else:
            await self._record_success()
            return result

    def __call__(self, func):
        """Decorator to wrap a function with circuit breaker logic."""

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.call(func, *args, **kwargs)

        wrapper.__circuit_breaker__ = self
        return wrapper

    def snapshot(self) -> dict[str, Any]:
        """Return the breaker state for status and health reporting."""
        return {
            "provider": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "consecutive_failures": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
        }

    def reset(self) -> None:
        """Reset the breaker to its initial CLOSED state."""
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.last_success_time = 0.0
        self.state = "CLOSED"
        self._probe_in_flight = False
        self._lock = asyncio.Lock()


PROVIDER_CIRCUIT_BREAKERS: dict[str, CircuitBreaker] = {
    provider: CircuitBreaker(name=provider) for provider in ("openai", "perplexity")
}
CIRCUIT_BREAKERS = PROVIDER_CIRCUIT_BREAKERS
circuit_breakers = PROVIDER_CIRCUIT_BREAKERS
provider_circuit_breakers = PROVIDER_CIRCUIT_BREAKERS
CircuitBreakerError = CircuitBreakerOpenError


def get_circuit_breaker(provider: str) -> CircuitBreaker:
    """Return the shared breaker for a provider, creating it once on first use."""
    breaker = PROVIDER_CIRCUIT_BREAKERS.get(provider)
    if breaker is None:
        breaker = CircuitBreaker(name=provider)
        PROVIDER_CIRCUIT_BREAKERS[provider] = breaker
    return breaker


def get_circuit_breaker_states() -> dict[str, dict[str, Any]]:
    """Return per-provider breaker state for the health endpoint."""
    return {
        provider: breaker.snapshot() for provider, breaker in PROVIDER_CIRCUIT_BREAKERS.items()
    }


def get_circuit_breaker_status() -> dict[str, dict[str, Any]]:
    """Alias for get_circuit_breaker_states()."""
    return get_circuit_breaker_states()


def reset_circuit_breakers() -> None:
    """Reset all provider breakers to CLOSED."""
    for breaker in PROVIDER_CIRCUIT_BREAKERS.values():
        breaker.reset()


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        max_elapsed: float | None = 90.0,
    ):
        """Initialize retry configuration values."""
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.max_elapsed = max_elapsed


DEFAULT_API_RETRY_CONFIG = RetryConfig(
    max_attempts=2,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
    max_elapsed=90.0,
)


async def retry_with_backoff(
    func: Callable,
    retry_config: RetryConfig,
    logger: logging.Logger,
    *args,
    **kwargs,
) -> Any:
    """Execute function with exponential backoff retry logic.

    Args:
        func: Function to execute
        retry_config: Retry configuration
        logger: Logger instance
        *args: Positional arguments passed to the function
        **kwargs: Keyword arguments passed to the function

    Returns:
        Function result on success

    Raises:
        Last exception if all retries exhausted
    """
    last_exception = None
    started_at = time.monotonic()

    for attempt in range(retry_config.max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            error_details = classify_error(e)

            if not _is_retryable_error(error_details, e):
                logger.exception("Non-retryable error in %s", func.__name__)
                raise

            if attempt >= retry_config.max_attempts - 1:
                logger.exception(
                    "All %s attempts failed for %s",
                    retry_config.max_attempts,
                    func.__name__,
                )
                break

            remaining = _remaining_time(started_at, retry_config)
            if remaining is not None and remaining <= 0:
                logger.exception(
                    "Retry deadline of %.1fs exceeded for %s",
                    retry_config.max_elapsed,
                    func.__name__,
                )
                break

            delay = _retry_delay(attempt, retry_config, error_details, e)
            if remaining is not None and delay >= remaining:
                logger.exception(
                    "Retry delay of %.1fs would exceed deadline of %.1fs for %s",
                    delay,
                    retry_config.max_elapsed,
                    func.__name__,
                )
                break

            logger.warning(
                "Attempt %d/%d failed for %s: %s. Retrying in %.1fs",
                attempt + 1,
                retry_config.max_attempts,
                func.__name__,
                e,
                delay,
            )
            await asyncio.sleep(delay)
    if last_exception is None:
        # Defensive guard: should not happen, but avoid raising NoneType
        msg = "Retry attempts exhausted without an exception captured"
        raise RuntimeError(msg)

    raise last_exception


def calculate_backoff_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate exponential backoff with full jitter."""
    delay = min(config.base_delay * (config.exponential_base**attempt), config.max_delay)

    if config.jitter:
        delay = secrets.SystemRandom().uniform(0, delay)

    return delay


_HTTP_STATUS_BAD_REQUEST = 400
_HTTP_STATUS_REQUEST_TIMEOUT = 408
_HTTP_STATUS_TOO_MANY_REQUESTS = 429
_HTTP_STATUS_SERVER_ERROR = 500

_RATE_LIMIT_MAX_RETRY_AFTER = 30.0
_HTTP_4XX_IN_MESSAGE_PATTERN = re.compile(r"(?<!\d)(4\d{2})(?!\d)")

_HTTPX_TIMEOUT_ERRORS: tuple[type[Exception], ...] = (httpx.TimeoutException,)
_HTTPX_TRANSPORT_ERRORS: tuple[type[Exception], ...] = (httpx.TransportError,)
_HTTPX_CONNECT_TIMEOUT_ERRORS: tuple[type[Exception], ...] = (httpx.ConnectTimeout,)

if httpx2 is not None:
    _HTTPX_TIMEOUT_ERRORS += (httpx2.TimeoutException,)
    _HTTPX_TRANSPORT_ERRORS += (httpx2.TransportError,)
    _HTTPX_CONNECT_TIMEOUT_ERRORS += (httpx2.ConnectTimeout,)


def _status_code_from_exception(exception: Exception) -> int | None:
    for source in (exception, getattr(exception, "response", None)):
        if source is None:
            continue
        for attribute in ("status_code", "status"):
            value = getattr(source, attribute, None)
            if isinstance(value, int):
                return value

    match = _HTTP_4XX_IN_MESSAGE_PATTERN.search(str(exception))
    return int(match.group(1)) if match else None


def _is_retryable_error(error_details: ErrorDetails, exception: Exception) -> bool:
    if isinstance(exception, CircuitBreakerOpenError):
        return False

    status_code = _status_code_from_exception(exception)

    if status_code == _HTTP_STATUS_TOO_MANY_REQUESTS:
        return True
    if (
        status_code is not None
        and _HTTP_STATUS_BAD_REQUEST <= status_code < _HTTP_STATUS_SERVER_ERROR
    ):
        return False
    if status_code is not None and status_code >= _HTTP_STATUS_SERVER_ERROR:
        return True

    if isinstance(exception, _HTTPX_CONNECT_TIMEOUT_ERRORS):
        return True

    return error_details.error_type not in {
        ErrorType.API_AUTH_ERROR,
        ErrorType.API_TIMEOUT,
        ErrorType.CONFIG_ERROR,
        ErrorType.VALIDATION_ERROR,
    }


def _retry_delay(
    attempt: int,
    config: RetryConfig,
    error_details: ErrorDetails,
    exception: Exception,
) -> float:
    is_rate_limit = (
        error_details.error_type == ErrorType.API_RATE_LIMIT
        or _status_code_from_exception(exception) == _HTTP_STATUS_TOO_MANY_REQUESTS
    )
    if is_rate_limit:
        retry_after = error_details.retry_after
        if retry_after is None:
            retry_after = _retry_after_from_response(getattr(exception, "response", None))
        if retry_after is not None:
            return min(max(float(retry_after), 0.0), _RATE_LIMIT_MAX_RETRY_AFTER)

    return calculate_backoff_delay(attempt, config)


def _remaining_time(started_at: float, config: RetryConfig) -> float | None:
    if config.max_elapsed is None:
        return None
    return config.max_elapsed - (time.monotonic() - started_at)


def _error_details(
    error_type: ErrorType,
    severity: ErrorSeverity,
    exception: Exception,
    user_message: str,
    retry_after: int | None = None,
) -> ErrorDetails:
    return ErrorDetails(
        error_type=error_type,
        severity=severity,
        message=str(exception),
        user_message=user_message,
        retry_after=retry_after,
        context={"exception_type": type(exception).__name__},
    )


def _get_response_header(response: Any, name: str) -> Any:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    try:
        value = headers.get(name)
    except (AttributeError, TypeError):
        return None

    if value is not None:
        return value

    try:
        for key in headers:
            if str(key).lower() == name.lower():
                return headers[key]
    except (AttributeError, TypeError):
        return None

    return None


def _parse_retry_after(value: Any) -> int | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        return max(0, math.ceil(float(text)))
    except (TypeError, ValueError, OverflowError):
        pass

    try:
        retry_at = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)

    return max(0, math.ceil((retry_at - datetime.now(UTC)).total_seconds()))


def _retry_after_from_response(response: Any) -> int | None:
    return _parse_retry_after(_get_response_header(response, "Retry-After"))


def _classify_api_status_error(exception: openai.APIStatusError) -> ErrorDetails:
    status_code = exception.status_code
    retry_after = _retry_after_from_response(exception.response)

    if status_code == _HTTP_STATUS_TOO_MANY_REQUESTS:
        return _error_details(
            ErrorType.API_RATE_LIMIT,
            ErrorSeverity.MEDIUM,
            exception,
            "⏱️ Service is busy. Please try again in a moment.",
            retry_after if retry_after is not None else 30,
        )

    if status_code in {401, 403}:
        return _error_details(
            ErrorType.API_AUTH_ERROR,
            ErrorSeverity.HIGH,
            exception,
            "🔐 Authentication issue. Please contact administrator.",
            retry_after,
        )

    if status_code == _HTTP_STATUS_REQUEST_TIMEOUT:
        return _error_details(
            ErrorType.API_TIMEOUT,
            ErrorSeverity.MEDIUM,
            exception,
            "🔧 Request timed out. Please try again.",
            retry_after if retry_after is not None else 10,
        )

    if status_code >= _HTTP_STATUS_SERVER_ERROR:
        return _error_details(
            ErrorType.API_SERVER_ERROR,
            ErrorSeverity.HIGH,
            exception,
            "🔧 Service temporarily unavailable. Please try again later.",
            retry_after if retry_after is not None else 60,
        )

    return _error_details(
        ErrorType.VALIDATION_ERROR,
        ErrorSeverity.MEDIUM,
        exception,
        "An unexpected error occurred. Please try again.",
        retry_after,
    )


def _classify_typed_error(exception: Exception) -> ErrorDetails | None:
    if isinstance(exception, CircuitBreakerOpenError):
        return _error_details(
            ErrorType.API_SERVER_ERROR,
            ErrorSeverity.HIGH,
            exception,
            ERROR_MESSAGES["ai_service_unavailable"],
            60,
        )

    if isinstance(exception, (openai.APITimeoutError, *_HTTPX_TIMEOUT_ERRORS)):
        return _error_details(
            ErrorType.API_TIMEOUT,
            ErrorSeverity.MEDIUM,
            exception,
            "🔧 Request timed out. Please try again.",
            10,
        )

    if isinstance(exception, (openai.APIConnectionError, *_HTTPX_TRANSPORT_ERRORS)):
        return _error_details(
            ErrorType.NETWORK_ERROR,
            ErrorSeverity.HIGH,
            exception,
            "🌐 Connection issue. Please check your network.",
            15,
        )

    if isinstance(exception, openai.APIStatusError):
        return _classify_api_status_error(exception)

    if isinstance(exception, discord.HTTPException):
        return _error_details(
            ErrorType.DISCORD_CONNECTION,
            ErrorSeverity.HIGH,
            exception,
            "🤖 Bot connection issue. Reconnecting...",
            _retry_after_from_response(getattr(exception, "response", None)),
        )

    return None


def classify_error(exception: Exception) -> ErrorDetails:
    """Classify exceptions into structured error details.

    Args:
        exception: Exception to classify

    Returns:
        ErrorDetails with classification and handling info
    """
    typed_details = _classify_typed_error(exception)
    if typed_details is not None:
        return typed_details

    error_msg = str(exception)
    error_type = ErrorType.UNKNOWN
    severity = ErrorSeverity.MEDIUM
    user_message = "An unexpected error occurred. Please try again."
    retry_after = None

    # Permanent billing/quota exhaustion — not a transient rate limit
    if (
        "insufficient_quota" in error_msg.lower()
        or "exceeded your current quota" in error_msg.lower()
    ):
        error_type = ErrorType.API_AUTH_ERROR
        severity = ErrorSeverity.HIGH
        user_message = "💳 API quota exhausted. Please check your OpenAI plan and billing details."

    # OpenAI/API specific errors
    elif "rate limit" in error_msg.lower() or "429" in error_msg:
        error_type = ErrorType.API_RATE_LIMIT
        severity = ErrorSeverity.MEDIUM
        user_message = "⏱️ Service is busy. Please try again in a moment."
        retry_after = 30

    elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
        error_type = ErrorType.API_TIMEOUT
        severity = ErrorSeverity.MEDIUM
        user_message = "🔧 Request timed out. Please try again."
        retry_after = 10

    elif "401" in error_msg or "unauthorized" in error_msg.lower():
        error_type = ErrorType.API_AUTH_ERROR
        severity = ErrorSeverity.HIGH
        user_message = "🔐 Authentication issue. Please contact administrator."

    elif any(
        re.search(rf"(?<!\d){code}(?!\d)", error_msg) for code in ["500", "502", "503", "504"]
    ):
        error_type = ErrorType.API_SERVER_ERROR
        severity = ErrorSeverity.HIGH
        user_message = "🔧 Service temporarily unavailable. Please try again later."
        retry_after = 60

    # Network/Connection errors
    elif any(term in error_msg.lower() for term in ["connection", "network", "dns"]):
        error_type = ErrorType.NETWORK_ERROR
        severity = ErrorSeverity.HIGH
        user_message = "🌐 Connection issue. Please check your network."
        retry_after = 15

    # Discord specific errors
    elif "discord" in error_msg.lower() or any(
        term in error_msg.lower() for term in ["websocket", "gateway"]
    ):
        error_type = ErrorType.DISCORD_CONNECTION
        severity = ErrorSeverity.HIGH
        user_message = "🤖 Bot connection issue. Reconnecting..."

    # Configuration errors
    elif any(term in error_msg.lower() for term in ["config", "missing", "invalid"]):
        error_type = ErrorType.CONFIG_ERROR
        severity = ErrorSeverity.CRITICAL
        user_message = "⚙️ Configuration issue. Please contact administrator."

    return _error_details(error_type, severity, exception, user_message, retry_after)


class ErrorTracker:
    """Track and aggregate error patterns for monitoring."""

    def __init__(self):
        """Initialize internal error counters and history buffer."""
        self.error_counts: dict[str, int] = {}
        self.error_history: list[dict[str, Any]] = []
        self.max_history = 1000
        self._lock = threading.Lock()

    def record_error(self, error_details: ErrorDetails, context: dict | None = None):
        """Record error occurrence for tracking and analysis."""
        with self._lock:
            error_key = f"{error_details.error_type.value}_{error_details.severity.value}"
            self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1

            error_record = {
                "timestamp": time.time(),
                "error_type": error_details.error_type.value,
                "severity": error_details.severity.value,
                "message": error_details.message,
                "context": context or {},
            }

            self.error_history.append(error_record)

            # Keep history bounded
            if len(self.error_history) > self.max_history:
                self.error_history = self.error_history[-self.max_history :]

    def get_error_summary(self, time_window: int = 3600) -> dict[str, Any]:
        """Get error summary for the specified time window (seconds)."""
        with self._lock:
            cutoff_time = time.time() - time_window
            recent_errors = [e for e in self.error_history if e["timestamp"] > cutoff_time]

            summary = {
                "total_errors": len(recent_errors),
                "error_types": {},
                "critical_count": 0,
                "high_count": 0,
            }

            for error in recent_errors:
                error_type = error["error_type"]
                severity = error["severity"]

                summary["error_types"][error_type] = summary["error_types"].get(error_type, 0) + 1

                if severity == "critical":
                    summary["critical_count"] += 1
                elif severity == "high":
                    summary["high_count"] += 1

            return summary


# Global error tracker instance
error_tracker = ErrorTracker()


def handle_api_error(func):
    """Decorator for enhanced API error handling with retries and circuit breaking.

    Example::

        @handle_api_error
        async def my_api_call():
            # API call code
            pass
    """

    @CircuitBreaker(failure_threshold=3, timeout=30)
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        func_logger = logging.getLogger(func.__module__)
        retry_config = RetryConfig(
            max_attempts=3,
            base_delay=0.1,
        )  # 3 attempts with short delay for tests

        # Use the original logger if it exists in kwargs without removing it.
        original_logger = kwargs.get("logger", func_logger)
        func_kwargs = dict(kwargs)
        func_kwargs.pop("logger", None)

        try:
            return await retry_with_backoff(
                func,
                retry_config,
                original_logger,
                *args,
                **func_kwargs,
            )

        except Exception as e:
            error_details = classify_error(e)
            error_tracker.record_error(error_details, {"function": func.__name__})

            # Log with appropriate level based on severity
            log_level = {
                ErrorSeverity.LOW: logging.INFO,
                ErrorSeverity.MEDIUM: logging.WARNING,
                ErrorSeverity.HIGH: logging.ERROR,
                ErrorSeverity.CRITICAL: logging.CRITICAL,
            }[error_details.severity]

            original_logger.log(
                log_level,
                "API error in %s: %s (Type: %s, Severity: %s)",
                func.__name__,
                error_details.message,
                error_details.error_type.value,
                error_details.severity.value,
                exc_info=error_details.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL],
            )

            raise

    return wrapper


def create_graceful_fallback(
    fallback_func: Callable,
    fallback_message: str = "Service temporarily unavailable",
):
    """Create a decorator that provides graceful fallback when main function fails.

    Args:
        fallback_func: Function to call if main function fails
        fallback_message: Message to use if both main and fallback fail
    """

    def decorator(main_func):
        @functools.wraps(main_func)
        async def wrapper(*args, **kwargs):
            logger = logging.getLogger(main_func.__module__)

            try:
                return await main_func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Main function %s failed: %s, trying fallback",
                    main_func.__name__,
                    e,
                )

                try:
                    return await fallback_func(*args, **kwargs)
                except Exception:
                    logger.exception("Both main and fallback failed for %s", main_func.__name__)
                    return fallback_message

        return wrapper

    return decorator


async def safe_discord_send(
    channel,
    content: str,
    logger: logging.Logger,
    max_retries: int = 3,
) -> bool:
    """Safely send message to Discord with retry logic and error handling.

    Args:
        channel: Discord channel object
        content: Message content
        logger: Logger instance
        max_retries: Maximum retry attempts

    Returns:
        bool: True if message sent successfully, False otherwise
    """
    for attempt in range(max_retries):
        try:
            await channel.send(content)
        except Exception as e:
            error_details = classify_error(e)

            if not _is_retryable_error(error_details, e):
                logger.exception("Non-retryable Discord send error")
                error_tracker.record_error(error_details, {"channel": str(channel)})
                break

            if attempt >= max_retries - 1:
                logger.exception("Failed to send Discord message after %s attempts", max_retries)
                error_tracker.record_error(error_details, {"channel": str(channel)})
                break

            delay = 2**attempt
            if isinstance(e, discord.HTTPException) and error_details.retry_after is not None:
                delay = min(float(error_details.retry_after), _RATE_LIMIT_MAX_RETRY_AFTER)
            logger.warning(
                "Discord send failed (attempt %d/%d): %s. Retrying in %ds",
                attempt + 1,
                max_retries,
                e,
                delay,
            )
            await asyncio.sleep(delay)
        else:
            return True
    return False
