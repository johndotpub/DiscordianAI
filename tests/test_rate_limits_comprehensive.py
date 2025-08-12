"""Comprehensive tests for src/rate_limits.py - Thread-safe rate limiting functionality.

This test suite covers:
- RateLimiter class initialization and thread safety
- check_rate_limit method with various scenarios
- get_user_status method for monitoring
- async check_rate_limit function wrapper
- Edge cases and error handling
- Thread safety verification
"""

import asyncio
import threading
import time
from unittest.mock import Mock

import pytest

from src.rate_limits import RateLimiter, check_rate_limit


class TestRateLimiterInitialization:
    """Test RateLimiter initialization."""

    def test_init_creates_empty_structures(self):
        """Test that RateLimiter initializes with empty data structures."""
        rate_limiter = RateLimiter()

        assert rate_limiter.last_command_timestamps == {}
        assert rate_limiter.last_command_count == {}
        assert hasattr(rate_limiter, "_lock")
        assert hasattr(rate_limiter, "_logger")

    def test_init_creates_rlock(self):
        """Test that RateLimiter uses RLock for thread safety."""
        rate_limiter = RateLimiter()

        # Verify it's an RLock (can be acquired multiple times by same thread)
        assert hasattr(rate_limiter._lock, "acquire")
        assert hasattr(rate_limiter._lock, "release")

        # RLock allows multiple acquisitions by same thread
        rate_limiter._lock.acquire()
        rate_limiter._lock.acquire()
        rate_limiter._lock.release()
        rate_limiter._lock.release()

    def test_init_creates_logger(self):
        """Test that RateLimiter creates a logger."""
        rate_limiter = RateLimiter()

        assert rate_limiter._logger is not None
        assert "RateLimiter" in rate_limiter._logger.name


class TestRateLimiterCheckRateLimit:
    """Test the check_rate_limit method."""

    def test_check_rate_limit_first_request(self):
        """Test first request from a user (should pass)."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345

        result = rate_limiter.check_rate_limit(user_id, 3, 60, logger)

        assert result is True
        assert rate_limiter.last_command_count[user_id] == 1
        assert user_id in rate_limiter.last_command_timestamps

        # Verify info logging for rate limit reset
        logger.info.assert_called_once()
        log_msg = logger.info.call_args[0][0]
        assert "Rate limit reset" in log_msg
        assert str(user_id) in log_msg

    def test_check_rate_limit_within_limit(self):
        """Test requests within rate limit (should pass)."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345

        # First request
        result1 = rate_limiter.check_rate_limit(user_id, 3, 60, logger)
        assert result1 is True

        # Second request (should still pass)
        logger.reset_mock()
        result2 = rate_limiter.check_rate_limit(user_id, 3, 60, logger)
        assert result2 is True
        assert rate_limiter.last_command_count[user_id] == 2

        # Verify info logging for successful rate limit check
        logger.info.assert_called_once()
        log_msg = logger.info.call_args[0][0]
        assert "Rate limit check passed" in log_msg
        assert "2/3" in log_msg

    def test_check_rate_limit_at_limit(self):
        """Test request exactly at the rate limit (should pass)."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345

        # Make requests up to the limit
        for _i in range(3):
            result = rate_limiter.check_rate_limit(user_id, 3, 60, logger)
            assert result is True

        assert rate_limiter.last_command_count[user_id] == 3

    def test_check_rate_limit_exceeds_limit(self):
        """Test request that exceeds rate limit (should fail)."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345

        # Use up the rate limit
        for _i in range(3):
            rate_limiter.check_rate_limit(user_id, 3, 60, logger)

        # Fourth request should fail
        logger.reset_mock()
        result = rate_limiter.check_rate_limit(user_id, 3, 60, logger)

        assert result is False
        assert rate_limiter.last_command_count[user_id] == 3  # Count doesn't increase

        # Verify warning logging for rate limit exceeded
        logger.warning.assert_called_once()
        log_msg = logger.warning.call_args[0][0]
        assert "Rate limit EXCEEDED" in log_msg
        assert "3/3" in log_msg
        assert str(user_id) in log_msg

    def test_check_rate_limit_window_expiry(self):
        """Test rate limit reset after window expiry."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345

        # Use up the rate limit
        for _i in range(3):
            rate_limiter.check_rate_limit(user_id, 3, 1, logger)  # 1 second window

        # Should fail initially
        result = rate_limiter.check_rate_limit(user_id, 3, 1, logger)
        assert result is False

        # Wait for window to expire
        time.sleep(1.1)

        # Should pass after window expiry
        logger.reset_mock()
        result = rate_limiter.check_rate_limit(user_id, 3, 1, logger)
        assert result is True
        assert rate_limiter.last_command_count[user_id] == 1  # Reset to 1

        # Verify info logging for rate limit reset
        logger.info.assert_called_once()
        log_msg = logger.info.call_args[0][0]
        assert "Rate limit reset" in log_msg

    def test_check_rate_limit_multiple_users(self):
        """Test rate limiting works independently for different users."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user1_id = 12345
        user2_id = 67890

        # User 1 uses up their limit
        for _i in range(3):
            result = rate_limiter.check_rate_limit(user1_id, 3, 60, logger)
            assert result is True

        # User 1 should now be rate limited
        result = rate_limiter.check_rate_limit(user1_id, 3, 60, logger)
        assert result is False

        # User 2 should still be able to make requests
        result = rate_limiter.check_rate_limit(user2_id, 3, 60, logger)
        assert result is True

    def test_check_rate_limit_thread_safety(self):
        """Test that rate limiting is thread-safe."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345
        results = []

        def make_request():
            result = rate_limiter.check_rate_limit(user_id, 5, 60, logger)
            results.append(result)

        # Create multiple threads making concurrent requests
        threads = []
        for _i in range(10):
            thread = threading.Thread(target=make_request)
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Should have exactly 5 successful requests (rate limit = 5)
        successful_requests = sum(1 for r in results if r)
        failed_requests = sum(1 for r in results if not r)

        assert successful_requests == 5
        assert failed_requests == 5
        assert len(results) == 10


class TestRateLimiterGetUserStatus:
    """Test the get_user_status method."""

    def test_get_user_status_new_user(self):
        """Test getting status for a user with no previous requests."""
        rate_limiter = RateLimiter()
        user_id = 12345

        status = rate_limiter.get_user_status(user_id, 5, 60)

        assert status["user_id"] == user_id
        assert status["current_count"] == 0
        assert status["remaining"] == 5
        assert status["window_reset_in"] == 0
        assert status["window_expired"] is True

    def test_get_user_status_within_window(self):
        """Test getting status for a user within the rate limit window."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345

        # Make some requests first
        for _i in range(3):
            rate_limiter.check_rate_limit(user_id, 5, 60, logger)

        status = rate_limiter.get_user_status(user_id, 5, 60)

        assert status["user_id"] == user_id
        assert status["current_count"] == 3
        assert status["remaining"] == 2
        assert status["window_reset_in"] > 0
        assert status["window_reset_in"] <= 60
        assert status["window_expired"] is False

    def test_get_user_status_window_expired(self):
        """Test getting status when the rate limit window has expired."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345

        # Make requests with a short window
        for _i in range(3):
            rate_limiter.check_rate_limit(user_id, 5, 1, logger)

        # Wait for window to expire
        time.sleep(1.1)

        status = rate_limiter.get_user_status(user_id, 5, 1)

        assert status["user_id"] == user_id
        assert status["current_count"] == 0
        assert status["remaining"] == 5
        assert status["window_reset_in"] == 0
        assert status["window_expired"] is True

    def test_get_user_status_at_limit(self):
        """Test getting status when user is at the rate limit."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345

        # Use up the rate limit
        for _i in range(5):
            rate_limiter.check_rate_limit(user_id, 5, 60, logger)

        status = rate_limiter.get_user_status(user_id, 5, 60)

        assert status["user_id"] == user_id
        assert status["current_count"] == 5
        assert status["remaining"] == 0
        assert status["window_reset_in"] > 0
        assert status["window_expired"] is False

    def test_get_user_status_thread_safety(self):
        """Test that get_user_status is thread-safe."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345
        statuses = []

        # Make some initial requests
        for _i in range(3):
            rate_limiter.check_rate_limit(user_id, 5, 60, logger)

        def get_status():
            status = rate_limiter.get_user_status(user_id, 5, 60)
            statuses.append(status)

        # Create multiple threads getting status concurrently
        threads = []
        for _i in range(5):
            thread = threading.Thread(target=get_status)
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All statuses should be consistent
        assert len(statuses) == 5
        for status in statuses:
            assert status["user_id"] == user_id
            assert status["current_count"] == 3
            assert status["remaining"] == 2


@pytest.mark.asyncio
class TestAsyncCheckRateLimit:
    """Test the async check_rate_limit function wrapper."""

    async def test_async_check_rate_limit_success(self):
        """Test successful async rate limit check."""
        rate_limiter = RateLimiter()
        mock_user = Mock()
        mock_user.id = 12345
        mock_user.name = "TestUser"
        logger = Mock()

        result = await check_rate_limit(mock_user, rate_limiter, 5, 60, logger)

        assert result is True

        # Verify debug logging for successful check
        logger.debug.assert_called_once()
        debug_msg = logger.debug.call_args[0][0]
        assert "Rate limit check successful" in debug_msg
        assert "TestUser" in debug_msg

    async def test_async_check_rate_limit_failure(self):
        """Test failed async rate limit check."""
        rate_limiter = RateLimiter()
        mock_user = Mock()
        mock_user.id = 12345
        mock_user.name = "TestUser"
        logger = Mock()

        # Use up the rate limit first
        for _i in range(3):
            await check_rate_limit(mock_user, rate_limiter, 3, 60, logger)

        # Fourth call should fail
        logger.reset_mock()
        result = await check_rate_limit(mock_user, rate_limiter, 3, 60, logger)

        assert result is False

        # Verify warning logging for exceeded limit (enhanced logging calls warning twice)
        assert logger.warning.call_count == 2  # Both RateLimiter and async wrapper log warnings
        # Each call in call_args_list is a unittest.mock._Call object;
        # call.args contains the positional arguments.
        warning_calls = [call.args[0] for call in logger.warning.call_args_list]
        assert any("Rate limit exceeded" in msg for msg in warning_calls)
        assert any("TestUser" in msg for msg in warning_calls)

    async def test_async_check_rate_limit_default_logger(self):
        """Test async rate limit check with default logger."""
        rate_limiter = RateLimiter()
        mock_user = Mock()
        mock_user.id = 12345
        mock_user.name = "TestUser"

        # Call without providing logger (should create default)
        result = await check_rate_limit(mock_user, rate_limiter, 5, 60)

        assert result is True

    async def test_async_check_rate_limit_exception_handling(self):
        """Test async rate limit check with exception handling."""
        rate_limiter = Mock()
        rate_limiter.check_rate_limit.side_effect = ValueError("Test error")

        mock_user = Mock()
        mock_user.id = 12345
        mock_user.name = "TestUser"
        logger = Mock()

        # Should fail open (return True) on exception
        result = await check_rate_limit(mock_user, rate_limiter, 5, 60, logger)

        assert result is True

        # Verify critical logging occurred and message content
        logger.critical.assert_called_once()
        critical_msg = logger.critical.call_args[0][0]
        assert "RATE_LIMITER_ERROR" in critical_msg
        assert "Failing open" in critical_msg

    async def test_async_check_rate_limit_none_logger(self):
        """Test async rate limit check with None logger creates default."""
        rate_limiter = RateLimiter()
        mock_user = Mock()
        mock_user.id = 12345
        mock_user.name = "TestUser"

        # Explicitly pass None for logger
        result = await check_rate_limit(mock_user, rate_limiter, 5, 60, None)

        assert result is True

    async def test_async_check_rate_limit_multiple_concurrent(self):
        """Test multiple concurrent async rate limit checks."""
        rate_limiter = RateLimiter()
        mock_user = Mock()
        mock_user.id = 12345
        mock_user.name = "TestUser"
        logger = Mock()

        # Create multiple concurrent checks
        tasks = []
        for _i in range(10):
            task = check_rate_limit(mock_user, rate_limiter, 5, 60, logger)
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        # Should have exactly 5 successful requests (rate limit = 5)
        successful_requests = sum(1 for r in results if r)
        failed_requests = sum(1 for r in results if not r)

        assert successful_requests == 5
        assert failed_requests == 5


class TestRateLimiterIntegration:
    """Integration tests combining multiple rate limiter features."""

    def test_rate_limiter_comprehensive_workflow(self):
        """Test complete rate limiter workflow with status checking."""
        rate_limiter = RateLimiter()
        logger = Mock()
        user_id = 12345

        # Check initial status
        initial_status = rate_limiter.get_user_status(user_id, 3, 60)
        assert initial_status["current_count"] == 0
        assert initial_status["remaining"] == 3

        # Make requests up to limit
        for i in range(3):
            result = rate_limiter.check_rate_limit(user_id, 3, 60, logger)
            assert result is True

            # Check status after each request
            status = rate_limiter.get_user_status(user_id, 3, 60)
            assert status["current_count"] == i + 1
            assert status["remaining"] == 3 - (i + 1)

        # Final status should show limit reached
        final_status = rate_limiter.get_user_status(user_id, 3, 60)
        assert final_status["current_count"] == 3
        assert final_status["remaining"] == 0

        # Next request should fail
        result = rate_limiter.check_rate_limit(user_id, 3, 60, logger)
        assert result is False

    @pytest.mark.asyncio
    async def test_sync_async_integration(self):
        """Test that sync and async methods work together correctly."""
        rate_limiter = RateLimiter()
        mock_user = Mock()
        mock_user.id = 12345
        mock_user.name = "TestUser"
        logger = Mock()

        # Make some requests via sync method
        for _i in range(2):
            result = rate_limiter.check_rate_limit(mock_user.id, 5, 60, logger)
            assert result is True

        # Check status
        status = rate_limiter.get_user_status(mock_user.id, 5, 60)
        assert status["current_count"] == 2
        assert status["remaining"] == 3

        # Make more requests via async method
        for _i in range(3):
            result = await check_rate_limit(mock_user, rate_limiter, 5, 60, logger)
            assert result is True

        # Final status should show limit reached
        final_status = rate_limiter.get_user_status(mock_user.id, 5, 60)
        assert final_status["current_count"] == 5
        assert final_status["remaining"] == 0

        # Next async request should fail
        result = await check_rate_limit(mock_user, rate_limiter, 5, 60, logger)
        assert result is False
