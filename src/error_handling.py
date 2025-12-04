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
from enum import Enum
import functools
import logging
import secrets
import time
from typing import Any


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
    ):
        """Initialize circuit breaker parameters."""
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def __call__(self, func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if self.state == "OPEN":
                if time.time() - self.last_failure_time > self.timeout:
                    self.state = "HALF_OPEN"
                else:
                    raise RuntimeError(f"Circuit breaker OPEN for {func.__name__}")

            try:
                result = await func(*args, **kwargs)
            except self.expected_exception:
                self.failure_count += 1
                self.last_failure_time = time.time()

                if self.failure_count >= self.failure_threshold:
                    self.state = "OPEN"

                raise
            else:
                if self.state == "HALF_OPEN":
                    self.state = "CLOSED"
                    self.failure_count = 0
                return result

        return wrapper


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
    ):
        """Initialize retry configuration values."""
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter


async def retry_with_backoff(
    func: Callable, retry_config: RetryConfig, logger: logging.Logger, *args, **kwargs
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

    for attempt in range(retry_config.max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:  # noqa: PERF203
            last_exception = e
            error_details = classify_error(e)

            # Don't retry certain error types
            if error_details.error_type in [ErrorType.API_AUTH_ERROR, ErrorType.CONFIG_ERROR]:
                logger.exception(f"Non-retryable error in {func.__name__}")
                raise

            if attempt >= retry_config.max_attempts - 1:
                logger.exception(
                    "All %s attempts failed for %s", retry_config.max_attempts, func.__name__
                )
                break

            delay = calculate_backoff_delay(attempt, retry_config)
            logger.warning(
                f"Attempt {attempt + 1}/{retry_config.max_attempts} failed for "
                f"{func.__name__}: {e}. "
                f"Retrying in {delay:.1f}s"
            )
            await asyncio.sleep(delay)

    raise last_exception


def calculate_backoff_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay with exponential backoff and jitter."""
    delay = min(config.base_delay * (config.exponential_base**attempt), config.max_delay)

    if config.jitter:
        # Add random jitter to prevent thundering herd
        # Use cryptographically secure random for jitter
        delay *= 0.5 + secrets.SystemRandom().random() * 0.5

    return delay


def classify_error(exception: Exception) -> ErrorDetails:
    """Classify exceptions into structured error details.

    Args:
        exception: Exception to classify

    Returns:
        ErrorDetails with classification and handling info
    """
    error_msg = str(exception)
    error_type = ErrorType.UNKNOWN
    severity = ErrorSeverity.MEDIUM
    user_message = "An unexpected error occurred. Please try again."
    retry_after = None

    # OpenAI/API specific errors
    if "rate limit" in error_msg.lower() or "429" in error_msg:
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

    elif "5" in error_msg and any(code in error_msg for code in ["500", "502", "503", "504"]):
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

    return ErrorDetails(
        error_type=error_type,
        severity=severity,
        message=error_msg,
        user_message=user_message,
        retry_after=retry_after,
        context={"exception_type": type(exception).__name__},
    )


class ErrorTracker:
    """Track and aggregate error patterns for monitoring."""

    def __init__(self):
        """Initialize internal error counters and history buffer."""
        self.error_counts: dict[str, int] = {}
        self.error_history: list[dict[str, Any]] = []
        self.max_history = 1000

    def record_error(self, error_details: ErrorDetails, context: dict | None = None):
        """Record error occurrence for tracking and analysis."""
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

    Usage:
        @handle_api_error
        async def my_api_call():
            # API call code
            pass
    """

    @CircuitBreaker(failure_threshold=3, timeout=30)
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        func_logger = logging.getLogger(func.__module__)
        retry_config = RetryConfig(max_attempts=2, base_delay=1.0)

        # Extract the original logger if it exists in kwargs to avoid conflicts
        original_logger = kwargs.pop("logger", func_logger)

        try:
            return await retry_with_backoff(func, retry_config, original_logger, *args, **kwargs)

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
                f"API error in {func.__name__}: {error_details.message} "
                f"(Type: {error_details.error_type.value}, "
                f"Severity: {error_details.severity.value})",
                exc_info=error_details.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL],
            )

            raise

    return wrapper


def create_graceful_fallback(
    fallback_func: Callable, fallback_message: str = "Service temporarily unavailable"
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
            except Exception as e:  # noqa: BLE001 - log and try fallback
                logger.warning(f"Main function {main_func.__name__} failed: {e}, trying fallback")

                try:
                    return await fallback_func(*args, **kwargs)
                except Exception:
                    logger.exception("Both main and fallback failed for %s", main_func.__name__)
                    return fallback_message

        return wrapper

    return decorator


async def safe_discord_send(
    channel, content: str, logger: logging.Logger, max_retries: int = 3
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
        except Exception as e:  # noqa: PERF203
            error_details = classify_error(e)

            if attempt >= max_retries - 1:
                logger.exception("Failed to send Discord message after %s attempts", max_retries)
                error_tracker.record_error(error_details, {"channel": str(channel)})
                break

            delay = 2**attempt  # Simple exponential backoff
            logger.warning(
                f"Discord send failed (attempt {attempt + 1}/{max_retries}): {e}. "
                f"Retrying in {delay}s"
            )
            await asyncio.sleep(delay)
        else:
            return True
    return False
