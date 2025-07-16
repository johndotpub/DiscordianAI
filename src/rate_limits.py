import logging
import time
import discord


class RateLimiter:
    """Class to handle rate limiting for users."""

    def __init__(self):
        """Initialize the RateLimiter with empty dictionaries."""
        self.last_command_timestamps = {}
        self.last_command_count = {}

    def check_rate_limit(
        self, user_id: int, rate_limit: int, rate_limit_per: int, logger: logging.Logger
    ) -> bool:
        """
        Check if a user has exceeded the rate limit.

        Args:
            user_id (int): The ID of the user.
            rate_limit (int): The maximum number of allowed commands.
            rate_limit_per (int): The time period for the rate limit.
            logger (logging.Logger): The logger instance.

        Returns:
            bool: True if the user is within the rate limit, False otherwise.
        """
        current_time = time.time()
        last_command_timestamp = self.last_command_timestamps.get(user_id, 0)
        last_command_count_user = self.last_command_count.get(user_id, 0)

        if current_time - last_command_timestamp > rate_limit_per:
            self.last_command_timestamps[user_id] = current_time
            self.last_command_count[user_id] = 1
            logger.info(f"Rate limit passed for user: {user_id}")
            return True

        if last_command_count_user < rate_limit:
            self.last_command_count[user_id] += 1
            logger.info(f"Rate limit passed for user: {user_id}")
            return True

        logger.info(f"Rate limit exceeded for user: {user_id}")
        return False


async def check_rate_limit(
    user: discord.User,
    rate_limiter: RateLimiter,
    rate_limit: int,
    rate_limit_per: int,
    logger: logging.Logger = None,
) -> bool:
    """
    Check if a user has exceeded the rate limit for sending messages.

    Args:
        user (discord.User): The user to check.
        rate_limiter (RateLimiter): The rate limiter instance.
        rate_limit (int): The maximum number of allowed commands.
        rate_limit_per (int): The time period for the rate limit.
        logger (logging.Logger, optional): The logger instance. Defaults to None.

    Returns:
        bool: True if the user is within the rate limit, False otherwise.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    return rate_limiter.check_rate_limit(user.id, rate_limit, rate_limit_per, logger)
