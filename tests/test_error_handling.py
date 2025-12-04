"""Comprehensive tests for src/error_handling.py - Error handling utilities.

This test suite covers:
- ErrorSeverity and ErrorType enums
- ErrorDetails dataclass
- CircuitBreaker pattern implementation
- RetryConfig and retry logic
- Error classification functions
- Safe Discord sending
- API error handling utilities
"""

from dataclasses import asdict
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.error_handling import (
    CircuitBreaker,
    ErrorDetails,
    ErrorSeverity,
    ErrorTracker,
    ErrorType,
    RetryConfig,
    calculate_backoff_delay,
    classify_error,
    create_graceful_fallback,
    error_tracker,
    handle_api_error,
    retry_with_backoff,
    safe_discord_send,
)


class TestEnums:
    """Test error handling enums."""

    def test_error_severity_values(self):
        """Test ErrorSeverity enum values."""
        assert ErrorSeverity.LOW.value == "low"
        assert ErrorSeverity.MEDIUM.value == "medium"
        assert ErrorSeverity.HIGH.value == "high"
        assert ErrorSeverity.CRITICAL.value == "critical"

    def test_error_type_values(self):
        """Test ErrorType enum values."""
        assert ErrorType.API_RATE_LIMIT.value == "api_rate_limit"
        assert ErrorType.API_TIMEOUT.value == "api_timeout"
        assert ErrorType.API_AUTH_ERROR.value == "api_auth_error"
        assert ErrorType.API_SERVER_ERROR.value == "api_server_error"
        assert ErrorType.NETWORK_ERROR.value == "network_error"
        assert ErrorType.DISCORD_CONNECTION.value == "discord_connection"
        assert ErrorType.CONFIG_ERROR.value == "config_error"
        assert ErrorType.VALIDATION_ERROR.value == "validation_error"
        assert ErrorType.UNKNOWN.value == "unknown"


class TestErrorDetails:
    """Test ErrorDetails dataclass."""

    def test_error_details_creation(self):
        """Test creating ErrorDetails instance."""
        details = ErrorDetails(
            error_type=ErrorType.API_RATE_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Rate limit exceeded",
            user_message="Please wait before trying again",
        )

        assert details.error_type == ErrorType.API_RATE_LIMIT
        assert details.severity == ErrorSeverity.HIGH
        assert details.message == "Rate limit exceeded"
        assert details.user_message == "Please wait before trying again"
        assert details.retry_after is None
        assert details.context is None

    def test_error_details_with_optional_fields(self):
        """Test ErrorDetails with optional fields."""
        context = {"user_id": 123, "action": "test"}
        details = ErrorDetails(
            error_type=ErrorType.API_TIMEOUT,
            severity=ErrorSeverity.MEDIUM,
            message="Request timed out",
            user_message="The request took too long",
            retry_after=30,
            context=context,
        )

        assert details.retry_after == 30
        assert details.context == context

    def test_error_details_dataclass_methods(self):
        """Test that ErrorDetails behaves as a proper dataclass."""
        details1 = ErrorDetails(
            error_type=ErrorType.UNKNOWN,
            severity=ErrorSeverity.LOW,
            message="Test",
            user_message="Test",
        )
        details2 = ErrorDetails(
            error_type=ErrorType.UNKNOWN,
            severity=ErrorSeverity.LOW,
            message="Test",
            user_message="Test",
        )

        # Test equality
        assert details1 == details2

        # Test conversion to dict
        details_dict = asdict(details1)
        assert details_dict["error_type"] == ErrorType.UNKNOWN
        assert details_dict["message"] == "Test"


class TestCircuitBreaker:
    """Test CircuitBreaker pattern implementation."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_state(self):
        """Test circuit breaker in closed state allows calls."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)

        @breaker
        async def test_func():
            return "success"

        result = await test_func()
        assert result == "success"
        assert breaker.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_circuit_breaker_failure_counting(self):
        """Test circuit breaker counts failures correctly."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)

        @breaker
        async def test_func():
            raise ValueError("Test error")

        # Should still be closed after first few failures
        for i in range(2):
            with pytest.raises(ValueError):
                await test_func()
            assert breaker.state == "CLOSED"
            assert breaker.failure_count == i + 1

        # Third failure should open the circuit
        with pytest.raises(ValueError):
            await test_func()
        assert breaker.state == "OPEN"
        assert breaker.failure_count == 3

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_state(self):
        """Test circuit breaker in open state fails fast."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=60)

        @breaker
        async def test_func():
            raise ValueError("Test error")

        # Trigger failures to open circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await test_func()

        assert breaker.state == "OPEN"

        # Should now fail fast without calling function
        with pytest.raises(Exception, match="Circuit breaker OPEN"):
            await test_func()

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_recovery(self):
        """Test circuit breaker half-open state and recovery."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=1)  # Short timeout

        @breaker
        async def test_func(should_succeed=False):
            if should_succeed:
                return "success"
            raise ValueError("Test error")

        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await test_func()
        assert breaker.state == "OPEN"

        # Wait for timeout
        time.sleep(1.1)

        # Next call should put it in HALF_OPEN, and success should close it
        result = await test_func(should_succeed=True)
        assert result == "success"
        assert breaker.state == "CLOSED"
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_failure(self):
        """Test circuit breaker half-open state with continued failure."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=1)

        @breaker
        async def test_func():
            raise ValueError("Test error")

        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await test_func()

        # Wait for timeout
        time.sleep(1.1)

        # Failure in half-open should reopen circuit
        with pytest.raises(ValueError):
            await test_func()
        assert breaker.state == "OPEN"

    @pytest.mark.asyncio
    async def test_circuit_breaker_custom_exception(self):
        """Test circuit breaker with custom expected exception."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=60, expected_exception=ValueError)

        @breaker
        async def test_func(error_type="value"):
            if error_type == "value":
                raise ValueError("Expected error")
            if error_type == "type":
                raise TypeError("Unexpected error")
            return "success"

        # ValueError should count toward failure threshold
        with pytest.raises(ValueError):
            await test_func("value")
        assert breaker.failure_count == 1

        # TypeError should propagate but not affect circuit
        with pytest.raises(TypeError):
            await test_func("type")
        assert breaker.failure_count == 1  # Should not increment

        # Another ValueError should trigger open state
        with pytest.raises(ValueError):
            await test_func("value")
        assert breaker.state == "OPEN"


class TestRetryConfig:
    """Test RetryConfig functionality."""

    def test_retry_config_creation(self):
        """Test creating RetryConfig instance."""
        config = RetryConfig(
            max_attempts=5, base_delay=2.0, max_delay=120.0, exponential_base=3.0, jitter=False
        )

        assert config.max_attempts == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 120.0
        assert config.exponential_base == 3.0
        assert config.jitter is False

    def test_retry_config_defaults(self):
        """Test RetryConfig with default values."""
        config = RetryConfig()

        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0
        assert config.jitter is True


@pytest.mark.asyncio
class TestRetryWithBackoff:
    """Test retry_with_backoff function."""

    async def test_retry_success_first_attempt(self):
        """Test function succeeds on first attempt."""
        call_count = 0

        async def test_func():
            nonlocal call_count
            call_count += 1
            return "success"

        mock_logger = Mock()
        config = RetryConfig(max_attempts=3)

        result = await retry_with_backoff(test_func, config, mock_logger)
        assert result == "success"
        assert call_count == 1

    async def test_retry_success_after_failures(self):
        """Test function succeeds after initial failures."""
        call_count = 0

        async def test_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary failure")
            return "success"

        mock_logger = Mock()
        config = RetryConfig(max_attempts=3, base_delay=0.1, jitter=False)

        result = await retry_with_backoff(test_func, config, mock_logger)
        assert result == "success"
        assert call_count == 3

    async def test_retry_exhausted(self):
        """Test retry exhaustion raises last exception."""
        call_count = 0

        async def test_func():
            nonlocal call_count
            call_count += 1
            raise ValueError(f"Failure {call_count}")

        mock_logger = Mock()
        config = RetryConfig(max_attempts=2, base_delay=0.1, jitter=False)

        with pytest.raises(ValueError, match="Failure 2"):
            await retry_with_backoff(test_func, config, mock_logger)
        assert call_count == 2

    async def test_retry_with_logger(self):
        """Test retry logging functionality."""
        call_count = 0

        async def test_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary failure")
            return "success"

        mock_logger = Mock()
        config = RetryConfig(max_attempts=3, base_delay=0.1, jitter=False)

        result = await retry_with_backoff(test_func, config, mock_logger)
        assert result == "success"

        # Should have logged retry attempts
        assert mock_logger.warning.call_count == 2  # Two retry warnings

    async def test_retry_non_retryable_error(self):
        """Test that certain errors are not retried."""
        call_count = 0

        async def test_func():
            nonlocal call_count
            call_count += 1
            raise Exception("401 Unauthorized: Invalid API key")  # Auth error

        mock_logger = Mock()
        config = RetryConfig(max_attempts=3, base_delay=0.1)

        with pytest.raises(Exception, match="401 Unauthorized"):
            await retry_with_backoff(test_func, config, mock_logger)

        # Should only be called once, not retried
        assert call_count == 1
        mock_logger.exception.assert_called_once()


class TestClassifyError:
    """Test error classification functionality."""

    def test_classify_api_rate_limit_error(self):
        """Test classification of rate limit errors."""
        error = Exception("Rate limit exceeded")
        details = classify_error(error)

        assert details.error_type == ErrorType.API_RATE_LIMIT
        assert details.severity == ErrorSeverity.MEDIUM
        assert "service is busy" in details.user_message.lower()

    def test_classify_api_timeout_error(self):
        """Test classification of timeout errors."""
        error = Exception("Request timed out after 30 seconds")
        details = classify_error(error)

        assert details.error_type == ErrorType.API_TIMEOUT
        assert details.severity == ErrorSeverity.MEDIUM
        assert "timed out" in details.user_message.lower()

    def test_classify_api_auth_error(self):
        """Test classification of authentication errors."""
        error = Exception("401 Unauthorized: Invalid API key")
        details = classify_error(error)

        assert details.error_type == ErrorType.API_AUTH_ERROR
        assert details.severity == ErrorSeverity.HIGH
        assert "authentication" in details.user_message.lower()

    def test_classify_api_server_error(self):
        """Test classification of server errors."""
        error = Exception("500 Internal Server Error")
        details = classify_error(error)

        assert details.error_type == ErrorType.API_SERVER_ERROR
        assert details.severity == ErrorSeverity.HIGH
        assert "service" in details.user_message.lower()

    def test_classify_network_error(self):
        """Test classification of network errors."""
        error = Exception("Connection failed: Unable to reach server")
        details = classify_error(error)

        assert details.error_type == ErrorType.NETWORK_ERROR
        assert details.severity == ErrorSeverity.HIGH
        assert "connection" in details.user_message.lower()

    def test_classify_discord_error(self):
        """Test classification of Discord-specific errors."""
        error = Exception("Discord API error: Forbidden")
        details = classify_error(error)

        assert details.error_type == ErrorType.DISCORD_CONNECTION
        assert details.severity == ErrorSeverity.HIGH

    def test_classify_unknown_error(self):
        """Test classification of unknown errors."""
        error = Exception("Some random error message")
        details = classify_error(error)

        assert details.error_type == ErrorType.UNKNOWN
        assert details.severity == ErrorSeverity.MEDIUM
        assert "unexpected error" in details.user_message.lower()

    def test_classify_error_context_format(self):
        """Test error classification context format."""
        error = ValueError("Test error")

        details = classify_error(error)

        assert details.context["exception_type"] == "ValueError"


@pytest.mark.asyncio
class TestSafeDiscordSend:
    """Test safe Discord message sending."""

    async def test_safe_discord_send_success(self):
        """Test successful message sending."""
        mock_channel = AsyncMock()
        mock_channel.send.return_value = Mock(id=12345)
        mock_logger = Mock()

        result = await safe_discord_send(mock_channel, "Test message", mock_logger)

        assert result is True
        mock_channel.send.assert_called_once_with("Test message")

    async def test_safe_discord_send_with_custom_retries(self):
        """Test message sending with custom retry count."""
        mock_channel = AsyncMock()
        mock_channel.send.return_value = Mock(id=12345)
        mock_logger = Mock()

        result = await safe_discord_send(mock_channel, "Test message", mock_logger, max_retries=5)

        assert result is True
        mock_channel.send.assert_called_once_with("Test message")

    async def test_safe_discord_send_failure(self):
        """Test message sending failure handling."""
        mock_channel = AsyncMock()
        mock_channel.send.side_effect = Exception("Discord API error")
        mock_logger = Mock()

        result = await safe_discord_send(mock_channel, "Test message", mock_logger, max_retries=2)

        assert result is False
        mock_logger.exception.assert_called_once()
        assert mock_channel.send.call_count == 2  # Should retry

    async def test_safe_discord_send_retry_success(self):
        """Test message sending succeeds after retry."""
        mock_channel = AsyncMock()
        # First call fails, second succeeds
        mock_channel.send.side_effect = [Exception("Temporary error"), Mock(id=12345)]
        mock_logger = Mock()

        with patch("asyncio.sleep") as mock_sleep:
            result = await safe_discord_send(mock_channel, "Test message", mock_logger)

        assert result is True
        assert mock_channel.send.call_count == 2
        mock_sleep.assert_called_once_with(1)  # 2^0 = 1 for first retry


@pytest.mark.asyncio
class TestHandleAPIError:
    """Test handle_api_error decorator functionality."""

    async def test_handle_api_error_decorator(self):
        """Test handle_api_error decorator with successful function."""

        @handle_api_error
        async def test_func():
            return "success"

        result = await test_func()
        assert result == "success"

    async def test_handle_api_error_decorator_with_retries(self):
        """Test handle_api_error decorator with retries."""
        call_count = 0

        @handle_api_error
        async def test_func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Temporary failure")
            return "success"

        result = await test_func()
        assert result == "success"
        assert call_count == 2

    async def test_handle_api_error_decorator_failure(self):
        """Test handle_api_error decorator with persistent failure."""
        call_count = 0

        @handle_api_error
        async def test_func():
            nonlocal call_count
            call_count += 1
            raise Exception("Persistent failure")

        with pytest.raises(Exception, match="Persistent failure"):
            await test_func()

        # Should have attempted retries
        assert call_count >= 2


class TestErrorTracker:
    """Test ErrorTracker functionality."""

    def test_error_tracker_record_error(self):
        """Test recording errors with ErrorTracker."""
        tracker = ErrorTracker()

        error_details = ErrorDetails(
            error_type=ErrorType.API_RATE_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Rate limit exceeded",
            user_message="Please wait",
        )

        context = {"user_id": 123}
        tracker.record_error(error_details, context)

        assert len(tracker.error_history) == 1
        assert tracker.error_counts["api_rate_limit_high"] == 1

    def test_error_tracker_summary(self):
        """Test getting error summary."""
        tracker = ErrorTracker()

        # Add some test errors
        for i in range(3):
            error_details = ErrorDetails(
                error_type=ErrorType.API_TIMEOUT,
                severity=ErrorSeverity.HIGH,
                message=f"Timeout {i}",
                user_message="Timeout occurred",
            )
            tracker.record_error(error_details)

        summary = tracker.get_error_summary()

        assert summary["total_errors"] == 3
        assert summary["error_types"]["api_timeout"] == 3
        assert summary["high_count"] == 3

    def test_error_tracker_history_limit(self):
        """Test error history size limit."""
        tracker = ErrorTracker()
        tracker.max_history = 5  # Set small limit for testing

        # Add more errors than the limit
        for i in range(10):
            error_details = ErrorDetails(
                error_type=ErrorType.UNKNOWN,
                severity=ErrorSeverity.LOW,
                message=f"Error {i}",
                user_message="Error occurred",
            )
            tracker.record_error(error_details)

        # Should only keep the last max_history items
        assert len(tracker.error_history) == 5


class TestCreateGracefulFallback:
    """Test create_graceful_fallback decorator."""

    @pytest.mark.asyncio
    async def test_graceful_fallback_success(self):
        """Test fallback when main function succeeds."""

        async def fallback_func():
            return "fallback"

        @create_graceful_fallback(fallback_func)
        async def main_func():
            return "success"

        result = await main_func()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_graceful_fallback_main_fails(self):
        """Test fallback when main function fails."""

        async def fallback_func():
            return "fallback"

        @create_graceful_fallback(fallback_func)
        async def main_func():
            raise Exception("Main failed")

        result = await main_func()
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_graceful_fallback_both_fail(self):
        """Test fallback when both functions fail."""

        async def fallback_func():
            raise Exception("Fallback failed")

        @create_graceful_fallback(fallback_func, "Default message")
        async def main_func():
            raise Exception("Main failed")

        result = await main_func()
        assert result == "Default message"


class TestCalculateBackoffDelay:
    """Test calculate_backoff_delay function."""

    def test_calculate_backoff_delay_basic(self):
        """Test basic backoff delay calculation."""
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=False)

        delay0 = calculate_backoff_delay(0, config)
        delay1 = calculate_backoff_delay(1, config)
        delay2 = calculate_backoff_delay(2, config)

        assert delay0 == 1.0  # 1.0 * (2.0 ** 0)
        assert delay1 == 2.0  # 1.0 * (2.0 ** 1)
        assert delay2 == 4.0  # 1.0 * (2.0 ** 2)

    def test_calculate_backoff_delay_max_limit(self):
        """Test backoff delay respects maximum limit."""
        config = RetryConfig(base_delay=10.0, exponential_base=3.0, max_delay=15.0, jitter=False)

        delay0 = calculate_backoff_delay(0, config)
        delay1 = calculate_backoff_delay(1, config)
        delay2 = calculate_backoff_delay(2, config)

        assert delay0 == 10.0  # base_delay
        assert delay1 == 15.0  # capped at max_delay (would be 30.0)
        assert delay2 == 15.0  # capped at max_delay (would be 90.0)

    def test_calculate_backoff_delay_with_jitter(self):
        """Test backoff delay with jitter."""
        config = RetryConfig(base_delay=2.0, exponential_base=2.0, jitter=True)

        # With jitter, delay should be between 50% and 100% of calculated value
        delay = calculate_backoff_delay(1, config)  # Should be around 2.0 * 2^1 = 4.0

        # With jitter, should be between 2.0 and 4.0
        assert 2.0 <= delay <= 4.0

    def test_calculate_backoff_delay_without_jitter(self):
        """Test backoff delay without jitter gives exact values."""
        config = RetryConfig(base_delay=3.0, exponential_base=2.0, jitter=False)

        delay = calculate_backoff_delay(2, config)  # 3.0 * (2.0 ** 2) = 12.0

        assert delay == 12.0


class TestGlobalErrorTracker:
    """Test global error_tracker instance."""

    def test_global_error_tracker_exists(self):
        """Test that global error tracker exists and is accessible."""
        assert error_tracker is not None
        assert isinstance(error_tracker, ErrorTracker)

    def test_global_error_tracker_functionality(self):
        """Test global error tracker basic functionality."""
        # Clear any existing history for clean test
        error_tracker.error_history.clear()
        error_tracker.error_counts.clear()

        error_details = ErrorDetails(
            error_type=ErrorType.NETWORK_ERROR,
            severity=ErrorSeverity.MEDIUM,
            message="Network timeout",
            user_message="Network issue",
        )

        error_tracker.record_error(error_details)

        assert len(error_tracker.error_history) == 1
        assert error_tracker.error_counts["network_error_medium"] == 1


class TestCircuitBreakerStateTransitions:
    """Test circuit breaker state transitions and recovery scenarios."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_to_open_transition(self):
        """Test circuit breaker transitions from CLOSED to OPEN after failures."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)

        @breaker
        async def failing_function():
            raise ValueError("Test error")

        # First failure should not open circuit
        with pytest.raises(ValueError):
            await failing_function()
        assert breaker.state == "CLOSED"
        assert breaker.failure_count == 1

        # Second failure should not open circuit
        with pytest.raises(ValueError):
            await failing_function()
        assert breaker.state == "CLOSED"
        assert breaker.failure_count == 2

        # Third failure should open circuit
        with pytest.raises(ValueError):
            await failing_function()
        assert breaker.state == "OPEN"
        assert breaker.failure_count == 3

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_blocks_requests(self):
        """Test that OPEN circuit breaker blocks requests immediately."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=60)
        breaker.state = "OPEN"
        breaker.last_failure_time = time.time()

        @breaker
        async def any_function():
            return "success"

        # Should raise RuntimeError immediately without calling function
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await any_function()

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_to_half_open_transition(self):
        """Test circuit breaker transitions from OPEN to HALF_OPEN after timeout."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=1)  # 1 second timeout
        breaker.state = "OPEN"
        breaker.last_failure_time = time.time() - 2  # 2 seconds ago

        @breaker
        async def test_function():
            return "success"

        # Should transition to HALF_OPEN and allow request, then to CLOSED on success
        result = await test_function()
        assert result == "success"
        # After successful call in HALF_OPEN, state should transition to CLOSED
        assert breaker.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_to_closed_on_success(self):
        """Test circuit breaker transitions from HALF_OPEN to CLOSED on success."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=1)
        breaker.state = "HALF_OPEN"
        breaker.failure_count = 2

        @breaker
        async def successful_function():
            return "success"

        result = await successful_function()
        assert result == "success"
        assert breaker.state == "CLOSED"
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_to_open_on_failure(self):
        """Test circuit breaker transitions from HALF_OPEN to OPEN on failure."""
        breaker = CircuitBreaker(failure_threshold=2, timeout=1)
        breaker.state = "HALF_OPEN"
        breaker.last_failure_time = time.time() - 2

        @breaker
        async def failing_function():
            raise ValueError("Test error")

        # Failure in HALF_OPEN should open circuit again
        with pytest.raises(ValueError):
            await failing_function()
        assert breaker.state == "OPEN"
        assert breaker.failure_count >= 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_resets_on_success(self):
        """Test that successful calls reset failure count in CLOSED state."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)

        @breaker
        async def sometimes_failing_function(should_fail: bool):
            if should_fail:
                raise ValueError("Test error")
            return "success"

        # Fail twice
        for _ in range(2):
            with pytest.raises(ValueError):
                await sometimes_failing_function(True)
        assert breaker.failure_count == 2

        # Success should not reset in CLOSED state (only in HALF_OPEN)
        result = await sometimes_failing_function(False)
        assert result == "success"
        # Failure count remains (only resets in HALF_OPEN)
        assert breaker.failure_count == 2


class TestRetryLogicScenarios:
    """Test retry logic with various failure scenarios."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        """Test retry succeeds after initial failure."""
        attempt_count = 0

        async def flaky_function():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise ConnectionError("Temporary failure")
            return "success"

        retry_config = RetryConfig(max_attempts=3, base_delay=0.1)
        logger = Mock()

        result = await retry_with_backoff(flaky_function, retry_config, logger)

        assert result == "success"
        assert attempt_count == 2
        assert logger.warning.called

    @pytest.mark.asyncio
    async def test_retry_exhausts_all_attempts(self):
        """Test retry exhausts all attempts and raises last exception."""
        attempt_count = 0

        async def always_failing_function():
            nonlocal attempt_count
            attempt_count += 1
            raise ConnectionError(f"Failure {attempt_count}")

        retry_config = RetryConfig(max_attempts=3, base_delay=0.1)
        logger = Mock()

        with pytest.raises(ConnectionError, match="Failure 3"):
            await retry_with_backoff(always_failing_function, retry_config, logger)

        assert attempt_count == 3
        assert logger.warning.call_count == 2  # Warnings for first 2 failures

    @pytest.mark.asyncio
    async def test_retry_skips_non_retryable_errors(self):
        """Test retry does not retry non-retryable error types."""
        attempt_count = 0

        async def auth_error_function():
            nonlocal attempt_count
            attempt_count += 1
            raise ValueError("401 Unauthorized")

        retry_config = RetryConfig(max_attempts=3, base_delay=0.1)
        logger = Mock()

        # Mock classify_error to return AUTH_ERROR
        with patch("src.error_handling.classify_error") as mock_classify:
            mock_classify.return_value = ErrorDetails(
                error_type=ErrorType.API_AUTH_ERROR,
                severity=ErrorSeverity.HIGH,
                message="401 Unauthorized",
                user_message="Auth error",
            )

            with pytest.raises(ValueError, match="401 Unauthorized"):
                await retry_with_backoff(auth_error_function, retry_config, logger)

        # Should not retry auth errors
        assert attempt_count == 1

    @pytest.mark.asyncio
    async def test_retry_exponential_backoff_delay(self):
        """Test that retry uses exponential backoff."""
        attempt_times = []

        async def failing_function():
            attempt_times.append(time.time())
            raise ConnectionError("Failure")

        retry_config = RetryConfig(
            max_attempts=3, base_delay=0.2, exponential_base=2.0, jitter=False
        )
        logger = Mock()

        with pytest.raises(ConnectionError):
            await retry_with_backoff(failing_function, retry_config, logger)

        # Check that delays increase exponentially
        assert len(attempt_times) == 3
        delay1 = attempt_times[1] - attempt_times[0]
        delay2 = attempt_times[2] - attempt_times[1]

        # Allow some tolerance for async timing
        assert 0.15 < delay1 < 0.25  # ~0.2s
        assert 0.35 < delay2 < 0.45  # ~0.4s (0.2 * 2)

    @pytest.mark.asyncio
    async def test_retry_respects_max_delay(self):
        """Test that retry respects max_delay configuration."""
        attempt_times = []

        async def failing_function():
            attempt_times.append(time.time())
            raise ConnectionError("Failure")

        retry_config = RetryConfig(
            max_attempts=5, base_delay=10.0, max_delay=0.5, exponential_base=2.0, jitter=False
        )
        logger = Mock()

        with pytest.raises(ConnectionError):
            await retry_with_backoff(failing_function, retry_config, logger)

        # Check that delays are capped at max_delay
        # Note: In parallel test execution, timing can vary significantly
        # so we use a generous tolerance
        assert len(attempt_times) >= 3
        for i in range(1, len(attempt_times)):
            delay = attempt_times[i] - attempt_times[i - 1]
            assert delay <= 3.0  # Allow generous tolerance for parallel execution overhead


class TestErrorRecoveryIntegration:
    """Test error recovery in integrated scenarios."""

    @pytest.mark.asyncio
    async def test_handle_api_error_with_circuit_breaker_and_retry(self):
        """Test handle_api_error decorator with both circuit breaker and retry."""
        call_count = 0

        @handle_api_error
        async def flaky_api_call():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary failure")
            return "success"

        logger = Mock()
        result = await flaky_api_call(logger=logger)

        assert result == "success"
        assert call_count == 3  # Retried until success

    @pytest.mark.asyncio
    async def test_circuit_breaker_with_multiple_concurrent_requests(self):
        """Test circuit breaker behavior with concurrent requests."""
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)
        failure_count = 0

        @breaker
        async def failing_function():
            nonlocal failure_count
            failure_count += 1
            raise ValueError("Test error")

        # Simulate concurrent failures
        tasks = [failing_function() for _ in range(5)]
        results = []

        for task in tasks:
            try:
                await task
            except (ValueError, RuntimeError) as e:  # noqa: PERF203
                results.append(type(e).__name__)

        # Should have some failures and potentially circuit open
        assert len(results) == 5
        assert failure_count >= 3  # At least threshold failures
