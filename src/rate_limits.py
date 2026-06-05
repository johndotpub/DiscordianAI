"""Thread-safe rate limiting for Discord bot users.

This module provides robust rate limiting functionality with thread-safety
to prevent race conditions in concurrent message processing scenarios.
"""

import logging
import threading
import time

import discord

FAIL_OPEN_LIMIT = 3


class RateLimiter:
    """Thread-safe rate limiter for Discord bot users.

    This class prevents users from exceeding specified rate limits by tracking
    their command usage in a thread-safe manner. It uses locks to prevent
    race conditions when multiple messages are processed concurrently.
    """

    def __init__(self):
        """Initialize the RateLimiter with thread-safe data structures.

        Creates empty dictionaries for tracking timestamps and counts,
        along with a threading lock for concurrent access protection.
        """
        self.last_command_timestamps: dict[int, float] = {}
        self.last_command_count: dict[int, int] = {}
        self._fail_open_errors = 0
        self._fail_open_cooldown_until = 0.0
        self._lock = threading.RLock()  # Use RLock for consistency with conversation manager
        self._logger = logging.getLogger(f"{__name__}.RateLimiter")

    @property
    def fail_open_errors(self) -> int:
        """Number of consecutive fail-open errors seen."""
        return self._fail_open_errors

    @fail_open_errors.setter
    def fail_open_errors(self, value: int) -> None:
        self._fail_open_errors = value

    @property
    def fail_open_cooldown_until(self) -> float:
        """Unix timestamp until fail-open cooldown expires."""
        return self._fail_open_cooldown_until

    @fail_open_cooldown_until.setter
    def fail_open_cooldown_until(self, value: float) -> None:
        self._fail_open_cooldown_until = value

    def check_rate_limit(
        self,
        user_id: int,
        rate_limit: int,
        rate_limit_window_seconds: int,
        logger: logging.Logger,
    ) -> bool:
        """Check if a user has exceeded their rate limit in a thread-safe manner.

        This method uses a threading lock to prevent race conditions where
        multiple concurrent requests could bypass rate limits.

        Args:
            user_id (int): The Discord user ID to check.
            rate_limit (int): Maximum number of allowed commands per time period.
            rate_limit_window_seconds (int): Time period in seconds for the rate limit window.
            logger (logging.Logger): Logger instance for rate limit events.

        Returns:
            bool: True if the user is within rate limits, False if exceeded.

        Thread Safety:
            Uses threading.Lock to ensure atomic operations on user data,
            preventing race conditions in concurrent message processing.
        """
        current_time = time.time()

        # Acquire lock to prevent race conditions
        with self._lock:
            last_timestamp = self.last_command_timestamps.get(user_id, 0)
            current_count = self.last_command_count.get(user_id, 0)

            # Check if rate limit window has expired - reset if so
            if current_time - last_timestamp > rate_limit_window_seconds:
                self.last_command_timestamps[user_id] = current_time
                self.last_command_count[user_id] = 1
                logger.info(
                    "Rate limit reset for user %s: 1/%d (window expired after %ds)",
                    user_id,
                    rate_limit,
                    rate_limit_window_seconds,
                )
                return True

            # Check if user is within rate limit
            if current_count < rate_limit:
                self.last_command_count[user_id] = current_count + 1
                logger.info(
                    "Rate limit check passed for user %s: %d/%d (%ds window)",
                    user_id,
                    self.last_command_count[user_id],
                    rate_limit,
                    rate_limit_window_seconds,
                )
                return True

            # Rate limit exceeded
            logger.warning(
                "Rate limit EXCEEDED for user %s: %d/%d in %ds window. Next reset in %.1fs",
                user_id,
                current_count,
                rate_limit,
                rate_limit_window_seconds,
                max(0, rate_limit_window_seconds - (current_time - last_timestamp)),
            )
            return False

    def get_user_status(
        self,
        user_id: int,
        rate_limit: int,
        rate_limit_window_seconds: int,
    ) -> dict:
        """Get detailed rate limit status for a user (for debugging/monitoring).

        Args:
            user_id (int): The Discord user ID to check.
            rate_limit (int): Maximum allowed commands per time period.
            rate_limit_window_seconds (int): Time period in seconds.

        Returns:
            Dict: Status information including current count, remaining, and reset time.
        """
        current_time = time.time()
        with self._lock:
            last_timestamp = self.last_command_timestamps.get(user_id, 0)
            current_count = self.last_command_count.get(user_id, 0)

            if current_time - last_timestamp > rate_limit_window_seconds:
                # Window expired
                return {
                    "user_id": user_id,
                    "current_count": 0,
                    "remaining": rate_limit,
                    "window_reset_in": 0,
                    "window_expired": True,
                }
            return {
                "user_id": user_id,
                "current_count": current_count,
                "remaining": max(0, rate_limit - current_count),
                "window_reset_in": max(
                    0,
                    rate_limit_window_seconds - (current_time - last_timestamp),
                ),
                "window_expired": False,
            }

async def check_rate_limit(
    user: discord.User,
    rate_limiter: RateLimiter,
    rate_limit: int,
    rate_limit_window_seconds: int,
    logger: logging.Logger | None = None,
) -> bool:
    """Async wrapper for rate limit checking with enhanced error handling.

    This function provides a Discord.py-friendly async interface to the
    thread-safe rate limiting functionality.

    Args:
        user (discord.User): The Discord user object to check.
        rate_limiter (RateLimiter): The rate limiter instance to use.
        rate_limit (int): Maximum commands allowed per time period.
        rate_limit_window_seconds (int): Time period in seconds for rate limiting.
        logger (logging.Logger, optional): Logger instance. Creates one if None.

    Returns:
        bool: True if user is within rate limits, False if exceeded.

    Raises:
        Exception: Re-raises any unexpected errors after logging them.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    try:
        result = rate_limiter.check_rate_limit(
            user.id,
            rate_limit,
            rate_limit_window_seconds,
            logger,
        )

    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.exception(
            "Unexpected error in rate limit check for user %s (ID: %s)",
            user.name,
            user.id,
        )
        now = time.time()
        fail_open_errors = rate_limiter.fail_open_errors
        if not isinstance(fail_open_errors, int):
            fail_open_errors = 0
        cooldown_until = rate_limiter.fail_open_cooldown_until
        if not isinstance(cooldown_until, (int, float)):
            cooldown_until = 0.0

        fail_open_errors += 1
        rate_limiter.fail_open_errors = fail_open_errors

        if now < cooldown_until:
            logger.warning(
                "RATE_LIMITER_ERROR: cooldown active, denying request after repeated failures"
            )
            return False

        # In case of error, allow the request (fail-open for availability)
        # but only for a limited number of consecutive failures.
        if fail_open_errors >= FAIL_OPEN_LIMIT:
            rate_limiter.fail_open_cooldown_until = now + 60
            rate_limiter.fail_open_errors = 0
            logger.critical(
                "RATE_LIMITER_ERROR: entering cooldown after repeated failures"
            )
        else:
            logger.critical(
                "RATE_LIMITER_ERROR: Failing open due to transient error: %s", exc
            )
        return True
    else:
        # Log successful rate limit checks at debug level
        rate_limiter.fail_open_errors = 0
        rate_limiter.fail_open_cooldown_until = 0.0
        if result:
            logger.debug("Rate limit check successful for %s (ID: %s)", user.name, user.id)
        else:
            logger.warning("Rate limit exceeded for %s (ID: %s)", user.name, user.id)
        return result
