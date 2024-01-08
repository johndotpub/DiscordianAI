from contextlib import contextmanager
import time
from unittest.mock import AsyncMock
import pytest
import logging

import bot
from bot import check_rate_limit


# Define a placeholder logger
logger = logging.getLogger('pytest_logger')
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)

RATE_LIMIT = 10
RATE_LIMIT_PER = 60

last_command_count = {}
last_command_timestamps = {}


@contextmanager
def patch_variables(module, variable_name, value):
    """Temporarily patches a variable in a module with a given value."""
    original_value = getattr(module, variable_name, None)
    setattr(module, variable_name, value)
    try:
        yield
    finally:
        setattr(module, variable_name, original_value)


async def run_test(user):
    with patch_variables(
        bot,
        'last_command_timestamps',
        {user.id: time.time() - 60}
    ), patch_variables(
        bot,
        'last_command_count',
        {user.id: 0}
    ), patch_variables(
        bot,
        'RATE_LIMIT_PER',
        RATE_LIMIT_PER
    ), patch_variables(
        bot,
        'RATE_LIMIT',
        RATE_LIMIT
    ):
        result = await check_rate_limit(user, logger)
        assert result is True
        assert bot.last_command_count.get(user.id, 0) == 1

        bot.last_command_count[user.id] = RATE_LIMIT
        result = await check_rate_limit(user, logger)
        assert result is False
        assert bot.last_command_count.get(user.id, 0) == RATE_LIMIT

        bot.last_command_timestamps[user.id] = time.time() - RATE_LIMIT_PER - 1
        result = await check_rate_limit(user, logger)
        assert result is True
        assert bot.last_command_count.get(user.id, 0) == 1


@pytest.mark.asyncio
async def test_check_rate_limit():
    user = AsyncMock()
    user.id = 123
    await run_test(user)
