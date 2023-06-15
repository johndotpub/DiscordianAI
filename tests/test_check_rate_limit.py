import time
from unittest.mock import AsyncMock
import asyncio
import pytest

import bot

from contextlib import contextmanager


@pytest.mark.asyncio
async def test_check_rate_limit():
    user = AsyncMock()
    user.id = 123

async def run_test():
    with patch_variables(
        bot, 'last_command_timestamps', {user.id: time.time() - 60}
    ), patch_variables(bot, 'last_command_count', {user.id: 0}), \
            patch_variables(bot, 'RATE_LIMIT_PER', RATE_LIMIT_PER), \
            patch_variables(bot, 'RATE_LIMIT', RATE_LIMIT):
        result = await check_rate_limit(user)
        assert result is True
        assert last_command_count[user.id] == 1

        last_command_count[user.id] = 3
        result = await check_rate_limit(user)
        assert result is False
        assert last_command_count[user.id] == 3

        last_command_timestamps[user.id] = time.time() - RATE_LIMIT_PER - 1
        result = await check_rate_limit(user)
        assert result is True
        assert last_command_count[user.id] == 1

    await run_test()


@contextmanager
def patch_variables(module, variable_name, value):
    """Temporarily patches a variable in a module with a given value."""
    original_value = getattr(module, variable_name, None)
    setattr(module, variable_name, value)
    try:
        yield
    finally:
        setattr(module, variable_name, original_value)
