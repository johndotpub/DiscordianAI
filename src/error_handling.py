"""Enhanced error handling utilities for critical system paths.

This module provides robust error handling patterns including:
- Exponential backoff with jitter
- Circuit breaker pattern
- Graceful degradation
- Centralized error classification
- Enhanced logging and monitoring
"""

import asyncio
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum
import functools
import logging
import math
import re
import secrets
import socket
import threading
import time
from typing import Any

import discord
import httpx
import openai

from .config import ERROR_MESSAGES
from .providers.registry import PROVIDERS

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
    retry_after: float | None = None
    context: dict[str, Any] | None = None


class ProviderCallError(RuntimeError):
    """A provider call that failed after classification.

    The processing wrappers raise this only when a caller asks to see failures;
    direct callers keep the legacy ``None`` result. ``details`` carries the one
    fixed user notice for the classified error.
    """

    def __init__(self, details: ErrorDetails, *, provider: str | None = None):
        """Build a typed provider failure around classified error details."""
        self.details = details
        self.provider = provider
        super().__init__(details.message)


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
        except self.expected_exception as exc:
            if _is_user_request_error(exc):
                # The provider answered and rejected this request. Release a
                # half-open probe without stamping a success or a failure.
                await self._release_probe()
            else:
                # Configuration errors (401, 403, 404) and transient provider
                # failures must surface through the breaker and /health.
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


PROVIDER_CIRCUIT_BREAKERS: dict[str, CircuitBreaker] = {
    provider: CircuitBreaker(name=provider) for provider, spec in PROVIDERS.items() if spec.breaker
}


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


RetryPredicate = Callable[[ErrorDetails, Exception], bool]
RetryDelayPolicy = Callable[[int, "RetryConfig", ErrorDetails, Exception], float]


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
        retry_if: RetryPredicate | None = None,
        delay_for: RetryDelayPolicy | None = None,
    ):
        """Initialize retry configuration values."""
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.max_elapsed = max_elapsed
        self.retry_if = retry_if
        self.delay_for = delay_for


DEFAULT_API_RETRY_CONFIG = RetryConfig(
    max_attempts=2,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
    max_elapsed=90.0,
)


def _callable_name(func: Callable) -> str:
    """Return a display name for a callable, falling back to its repr."""
    return getattr(func, "__name__", repr(func))


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
            retry_if = retry_config.retry_if or _is_retryable_error

            if not retry_if(error_details, e):
                logger.error(  # noqa: TRY400 - the caller logs one traceback
                    "Non-retryable error in %s (%s)",
                    _callable_name(func),
                    type(e).__name__,
                )
                raise

            if attempt >= retry_config.max_attempts - 1:
                logger.error(  # noqa: TRY400 - the caller logs one traceback
                    "All %s attempts failed for %s (%s)",
                    retry_config.max_attempts,
                    _callable_name(func),
                    type(e).__name__,
                )
                break

            remaining = _remaining_time(started_at, retry_config)
            if remaining is not None and remaining <= 0:
                logger.error(  # noqa: TRY400 - the caller logs one traceback
                    "Retry deadline of %.1fs exceeded for %s (%s)",
                    retry_config.max_elapsed,
                    _callable_name(func),
                    type(e).__name__,
                )
                break

            delay_policy = retry_config.delay_for or _retry_delay
            delay = delay_policy(attempt, retry_config, error_details, e)
            if remaining is not None and delay >= remaining:
                logger.error(  # noqa: TRY400 - the caller logs one traceback
                    "Retry delay of %.1fs would exceed deadline of %.1fs for %s (%s)",
                    delay,
                    retry_config.max_elapsed,
                    _callable_name(func),
                    type(e).__name__,
                )
                break

            logger.warning(
                "Attempt %d/%d failed for %s: %s. Retrying in %.1fs",
                attempt + 1,
                retry_config.max_attempts,
                _callable_name(func),
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
HTTP_STATUS_TOO_MANY_REQUESTS = 429
_HTTP_STATUS_SERVER_ERROR = 500
_CONFIGURATION_ERROR_STATUSES = frozenset({401, 403, 404})
_MODEL_CONFIGURATION_ERROR_MARKERS = frozenset({"invalid_model", "model_not_found"})

_RATE_LIMIT_MAX_RETRY_AFTER = 30.0
# Match a status token in prose, never the port in "host:443" or a dotted
# version/IP fragment.
_HTTP_4XX_IN_MESSAGE_PATTERN = re.compile(r"(?<![\d:.])(4\d{2})(?![\d:])")

NETWORK_ERROR_USER_MESSAGE = "🌐 I couldn't reach the AI service. Please try again shortly."
DISCORD_CONNECTION_USER_MESSAGE = (
    "🤖 I'm having trouble connecting to Discord. Please try again shortly."
)
QUOTA_EXHAUSTED_USER_MESSAGE = "💳 API quota exhausted. The provider returned insufficient quota."
_QUOTA_EXHAUSTED_MARKERS = ("insufficient_quota", "exceeded your current quota")

_HTTPX_TIMEOUT_ERRORS: tuple[type[Exception], ...] = (httpx.TimeoutException,)
_HTTPX_TRANSPORT_ERRORS: tuple[type[Exception], ...] = (httpx.TransportError,)
_HTTPX_CONNECT_ERRORS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
)
_HTTPX_AFTER_REQUEST_ERRORS: tuple[type[Exception], ...] = (
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.ProtocolError,
    httpx.WriteError,
)

if httpx2 is not None:
    _HTTPX_TIMEOUT_ERRORS += (httpx2.TimeoutException,)
    _HTTPX_TRANSPORT_ERRORS += (httpx2.TransportError,)
    _HTTPX_CONNECT_ERRORS += (httpx2.ConnectError, httpx2.ConnectTimeout)
    _HTTPX_AFTER_REQUEST_ERRORS += (
        httpx2.ReadError,
        httpx2.ReadTimeout,
        httpx2.RemoteProtocolError,
        httpx2.ProtocolError,
        httpx2.WriteError,
    )


def _structured_status_code(exception: Exception) -> int | None:
    """Return an HTTP status from the exception or its response, without parsing text."""
    for source in (exception, getattr(exception, "response", None)):
        if source is None:
            continue
        for attribute in ("status_code", "status"):
            value = getattr(source, attribute, None)
            if isinstance(value, int):
                return value
    return None


def _status_code_from_exception(exception: Exception) -> int | None:
    status_code = _structured_status_code(exception)
    if status_code is not None:
        return status_code

    match = _HTTP_4XX_IN_MESSAGE_PATTERN.search(str(exception))
    return int(match.group(1)) if match else None


def _exception_chain(exception: Exception) -> list[BaseException]:
    """Return the explicit ``raise ... from`` cause chain, nearest first."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exception
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__
    return chain


def _chain_matches(exception: Exception, types: tuple[type[Exception], ...]) -> bool:
    return any(isinstance(item, types) for item in _exception_chain(exception))


def _iter_error_body_strings(value: Any) -> Iterator[str]:
    """Yield strings from a structured error body without assuming its shape."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_error_body_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_error_body_strings(item)


def _message_names_an_unsupported_model(message: str) -> bool:
    """Return True when provider prose says the model itself is the problem."""
    lowered = message.lower()
    if not re.search(r"\bmodel\b", lowered):
        return False
    return any(phrase in lowered for phrase in ("is not supported", "not found", "does not exist"))


def _model_configuration_error(exception: Exception) -> bool:
    """Return True when a 400 reports a retired or unknown model.

    Providers put the machine-readable reason in a structured error object.
    Both Perplexity's Agent API (``error.type: invalid_model``) and the
    OpenAI-style ``error.code: model_not_found`` are configuration errors.
    A 400 that names the model itself is too: ``param`` is ``"model"``, or the
    message combines the word ``model`` with ``is not supported``, ``not
    found``, or ``does not exist``. The real SDK exposes the inner error object
    as ``body`` and coerces the recorded numeric ``code`` to the string
    ``"400"``, so the markers are read from either wrapping.
    """
    candidates: list[str] = []
    body = getattr(exception, "body", None)
    structured: Mapping | None = None
    if isinstance(body, Mapping):
        inner = body.get("error", body)
        if isinstance(inner, Mapping):
            structured = inner
            for key in ("type", "code"):
                value = inner.get(key)
                if isinstance(value, str):
                    candidates.append(value)
        for key in ("type", "code"):
            value = body.get(key)
            if isinstance(value, str):
                candidates.append(value)
    for attribute in ("type", "code"):
        value = getattr(exception, attribute, None)
        if isinstance(value, str):
            candidates.append(value)
    if any(
        candidate.strip().lower() in _MODEL_CONFIGURATION_ERROR_MARKERS for candidate in candidates
    ):
        return True

    if structured is not None:
        param = structured.get("param")
        if isinstance(param, str) and param.strip().lower() == "model":
            return True
        message = structured.get("message")
        if isinstance(message, str) and _message_names_an_unsupported_model(message):
            return True
    return False


def _is_quota_exhausted(exception: Exception) -> bool:
    """Return True when the structured error body reports exhausted quota."""
    candidates = [
        getattr(exception, "code", None),
        getattr(exception, "type", None),
        getattr(exception, "body", None),
    ]
    for candidate in candidates:
        for text in _iter_error_body_strings(candidate):
            lowered = text.lower()
            if any(marker in lowered for marker in _QUOTA_EXHAUSTED_MARKERS):
                return True
    return False


def _is_user_request_error(exception: Exception) -> bool:
    """Return True for a deterministic 4xx caused by this request.

    A user-caused request error (400, 409, 413, 422, and other client errors)
    proves the provider answered; it must neither push the breaker towards OPEN
    nor stamp a success. Configuration errors (401, 403, 404, and a 400 whose
    structured type or code marks the model invalid or missing) are different:
    a revoked key or retired model fails every call and must make /health
    report the provider degraded or unhealthy. Timeouts, 408, 429, 5xx, and
    unclassified errors count as provider failures.
    """
    if isinstance(exception, CircuitBreakerOpenError):
        return False

    status_code = _structured_status_code(exception)
    if status_code is not None:
        if not _HTTP_STATUS_BAD_REQUEST <= status_code < _HTTP_STATUS_SERVER_ERROR:
            return False
        if status_code == _HTTP_STATUS_BAD_REQUEST and _model_configuration_error(exception):
            return False
        return status_code not in {
            *_CONFIGURATION_ERROR_STATUSES,
            _HTTP_STATUS_REQUEST_TIMEOUT,
            HTTP_STATUS_TOO_MANY_REQUESTS,
        }

    return classify_error(exception).error_type == ErrorType.VALIDATION_ERROR


def is_retryable_status(status: int | None) -> bool:
    """Return whether an HTTP status is a transient failure worth retrying."""
    if status is None:
        return False
    return status == HTTP_STATUS_TOO_MANY_REQUESTS or status >= _HTTP_STATUS_SERVER_ERROR


def _is_retryable_error(  # noqa: PLR0911 - one branch per retry policy rule
    error_details: ErrorDetails, exception: Exception
) -> bool:
    if isinstance(exception, CircuitBreakerOpenError):
        return False
    if _is_quota_exhausted(exception):
        return False

    status_code = _status_code_from_exception(exception)
    if status_code is not None:
        return is_retryable_status(status_code)

    if isinstance(exception, (ConnectionRefusedError, socket.gaierror)):
        # Refused before a connection existed and DNS failure both prove the
        # request never reached the provider.
        return True

    if isinstance(exception, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
        # These three can arrive after the request was sent, so a repeat is
        # not provably safe. The bare ConnectionError keeps its historical
        # retryable classification for callers that use it as a connect alias.
        return False

    if isinstance(exception, (openai.APITimeoutError, *_HTTPX_TIMEOUT_ERRORS)):
        # The SDK wraps every transport timeout in APITimeoutError. Only a
        # connect timeout proves the request was never sent and safe to retry.
        return _chain_matches(exception, _HTTPX_CONNECT_ERRORS)

    if isinstance(exception, (openai.APIConnectionError, *_HTTPX_TRANSPORT_ERRORS)):
        # Read, write, and protocol errors can arrive after the provider
        # already served the request; a connect error cannot.
        return not _chain_matches(exception, _HTTPX_AFTER_REQUEST_ERRORS)

    return error_details.error_type not in {
        ErrorType.API_AUTH_ERROR,
        ErrorType.API_TIMEOUT,
        ErrorType.CONFIG_ERROR,
        ErrorType.UNKNOWN,
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
        or _status_code_from_exception(exception) == HTTP_STATUS_TOO_MANY_REQUESTS
    )
    if is_rate_limit:
        retry_after = _bounded_retry_after(error_details.retry_after)
        if retry_after is None:
            retry_after = retry_after_seconds(
                getattr(getattr(exception, "response", None), "headers", None)
            )
        if retry_after is not None:
            return retry_after

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
    retry_after: float | None = None,
) -> ErrorDetails:
    return ErrorDetails(
        error_type=error_type,
        severity=severity,
        message=str(exception),
        user_message=user_message,
        retry_after=retry_after,
        context={"exception_type": type(exception).__name__},
    )


def _header_value(headers: Any, name: str) -> Any:
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


def _bounded_retry_after(value: Any) -> float | None:
    """Return a finite, non-negative Retry-After bounded by the policy cap."""
    if value is None:
        return None
    try:
        delay = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(delay) or delay < 0.0:
        return None
    return min(delay, _RATE_LIMIT_MAX_RETRY_AFTER)


def retry_after_seconds(headers: Any) -> float | None:
    """Parse a Retry-After header and bound it to the retry policy maximum.

    A header that is not a finite, non-negative number of seconds and is not a
    valid HTTP date returns ``None`` so the caller uses normal backoff instead
    of sleeping on ``nan`` or a huge value.
    """
    value = _header_value(headers, "Retry-After")
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        delay = float(text)
    except (TypeError, ValueError, OverflowError):
        pass
    else:
        return _bounded_retry_after(delay)

    try:
        retry_at = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)

    return min(
        max((retry_at - datetime.now(UTC)).total_seconds(), 0.0),
        _RATE_LIMIT_MAX_RETRY_AFTER,
    )


def _classify_api_status_error(exception: openai.APIStatusError) -> ErrorDetails:
    status_code = exception.status_code
    retry_after = retry_after_seconds(getattr(exception.response, "headers", None))

    if _is_quota_exhausted(exception):
        return _error_details(
            ErrorType.API_AUTH_ERROR,
            ErrorSeverity.HIGH,
            exception,
            QUOTA_EXHAUSTED_USER_MESSAGE,
            retry_after,
        )

    if status_code == HTTP_STATUS_TOO_MANY_REQUESTS:
        # A missing header keeps the historical 30-second default. A header
        # that is present but unusable (nan, negative, absurd) leaves the delay
        # to normal backoff instead of sleeping on a bogus value.
        if (
            retry_after is None
            and _header_value(getattr(exception.response, "headers", None), "Retry-After") is None
        ):
            retry_after = 30
        return _error_details(
            ErrorType.API_RATE_LIMIT,
            ErrorSeverity.MEDIUM,
            exception,
            "⏱️ Service is busy. Please try again in a moment.",
            retry_after,
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

    if isinstance(
        exception,
        (ConnectionError, socket.gaierror, openai.APIConnectionError, *_HTTPX_TRANSPORT_ERRORS),
    ):
        return _error_details(
            ErrorType.NETWORK_ERROR,
            ErrorSeverity.HIGH,
            exception,
            NETWORK_ERROR_USER_MESSAGE,
            15,
        )

    if isinstance(exception, openai.APIStatusError):
        return _classify_api_status_error(exception)

    if isinstance(exception, discord.HTTPException):
        return _error_details(
            ErrorType.DISCORD_CONNECTION,
            ErrorSeverity.HIGH,
            exception,
            DISCORD_CONNECTION_USER_MESSAGE,
            retry_after_seconds(getattr(getattr(exception, "response", None), "headers", None)),
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
    if any(marker in error_msg.lower() for marker in _QUOTA_EXHAUSTED_MARKERS):
        error_type = ErrorType.API_AUTH_ERROR
        severity = ErrorSeverity.HIGH
        user_message = QUOTA_EXHAUSTED_USER_MESSAGE

    # OpenAI/API specific errors
    elif "rate limit" in error_msg.lower() or re.search(r"\b429\b", error_msg):
        error_type = ErrorType.API_RATE_LIMIT
        severity = ErrorSeverity.MEDIUM
        user_message = "⏱️ Service is busy. Please try again in a moment."
        retry_after = 30

    elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
        error_type = ErrorType.API_TIMEOUT
        severity = ErrorSeverity.MEDIUM
        user_message = "🔧 Request timed out. Please try again."
        retry_after = 10

    elif re.search(r"\b401\b", error_msg) or "unauthorized" in error_msg.lower():
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
        user_message = NETWORK_ERROR_USER_MESSAGE
        retry_after = 15

    # Discord specific errors
    elif "discord" in error_msg.lower() or any(
        term in error_msg.lower() for term in ["websocket", "gateway"]
    ):
        error_type = ErrorType.DISCORD_CONNECTION
        severity = ErrorSeverity.HIGH
        user_message = DISCORD_CONNECTION_USER_MESSAGE

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


# Global error tracker instance
error_tracker = ErrorTracker()


def _is_retryable_discord_error(_error_details: ErrorDetails, exception: Exception) -> bool:
    if isinstance(exception, CircuitBreakerOpenError):
        return False
    if isinstance(exception, discord.Forbidden):
        return False

    status_code = _status_code_from_exception(exception)
    if status_code is not None:
        return is_retryable_status(status_code)

    return True


def _discord_retry_delay(
    attempt: int,
    config: RetryConfig,
    error_details: ErrorDetails,
    exception: Exception,
) -> float:
    retry_after = getattr(exception, "retry_after", None)
    if retry_after is None and isinstance(exception, discord.HTTPException):
        retry_after = error_details.retry_after
    if retry_after is not None:
        return min(max(float(retry_after), 0.0), _RATE_LIMIT_MAX_RETRY_AFTER)

    return calculate_backoff_delay(attempt, config)


def _discord_retry_config(max_retries: int) -> RetryConfig:
    return RetryConfig(
        max_attempts=max_retries,
        base_delay=1.0,
        max_delay=float("inf"),
        exponential_base=2.0,
        jitter=False,
        max_elapsed=None,
        retry_if=_is_retryable_discord_error,
        delay_for=_discord_retry_delay,
    )


async def safe_discord_send(
    channel,
    content: str,
    logger: logging.Logger,
    max_retries: int = 3,
    *,
    mention_users: Sequence[Any] | None = None,
) -> bool:
    """Safely send message to Discord with retry logic and error handling.

    Args:
        channel: Discord channel object
        content: Message content
        logger: Logger instance
        max_retries: Maximum retry attempts
        mention_users: Optional users the notice may mention. ``None`` keeps a
            bare channel send; a sequence routes through the delivery helper,
            which owns the ``AllowedMentions`` construction.

    Returns:
        bool: True if message sent successfully, False otherwise
    """

    async def _send_once() -> None:
        if mention_users is None:
            await channel.send(content)
            return

        from .message_splitter import _deliver  # noqa: PLC0415 - avoids an import cycle

        await _deliver(channel, content, mention_users=mention_users)

    try:
        await retry_with_backoff(_send_once, _discord_retry_config(max_retries), logger)
    except Exception as exc:
        logger.exception("Failed to send Discord message after retries")
        error_tracker.record_error(classify_error(exc), {"channel": str(channel)})
        return False
    return True
