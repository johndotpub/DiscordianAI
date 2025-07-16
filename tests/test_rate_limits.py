import logging
import time
from unittest.mock import AsyncMock

import pytest

from src.rate_limits import RateLimiter

# Define a placeholder logger
logger = logging.getLogger("pytest_logger")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)

RATE_LIMIT = 10
RATE_LIMIT_PER = 60


def run_test(user, rate_limiter):
    # Simulate first command
    result = rate_limiter.check_rate_limit(user.id, RATE_LIMIT, RATE_LIMIT_PER, logger)
    assert result is True
    assert rate_limiter.last_command_count.get(user.id, 0) == 1

    # Simulate reaching rate limit
    rate_limiter.last_command_count[user.id] = RATE_LIMIT
    result = rate_limiter.check_rate_limit(user.id, RATE_LIMIT, RATE_LIMIT_PER, logger)
    assert result is False
    assert rate_limiter.last_command_count.get(user.id, 0) == RATE_LIMIT

    # Simulate time passing to reset rate limit
    rate_limiter.last_command_timestamps[user.id] = time.time() - RATE_LIMIT_PER - 1
    result = rate_limiter.check_rate_limit(user.id, RATE_LIMIT, RATE_LIMIT_PER, logger)
    assert result is True
    assert rate_limiter.last_command_count.get(user.id, 0) == 1


@pytest.mark.asyncio
async def test_check_rate_limit():
    user = AsyncMock()
    user.id = 123
    rate_limiter = RateLimiter()
    run_test(user, rate_limiter)
