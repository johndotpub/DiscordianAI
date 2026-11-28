"""Authorisation matrix for the real message router."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import message_router
from tests.helpers import (
    FakeChannel,
    FakeDMChannel,
    FakeGuild,
    FakeThread,
    FakeUser,
    bot_for_guild,
    guild_with_channel,
    make_router_message,
)

pytestmark = pytest.mark.usefixtures("fake_discord_types")


@pytest.fixture
def deps():
    logger = logging.getLogger("router-auth-test")
    logger.addHandler(logging.NullHandler())
    return {"logger": logger}


@pytest.fixture
def spies(monkeypatch):
    channel = AsyncMock()
    dm = AsyncMock()
    monkeypatch.setattr(message_router, "process_channel_message", channel)
    monkeypatch.setattr(message_router, "process_dm_message", dm)
    return SimpleNamespace(channel=channel, dm=dm)


_message = make_router_message
_guild_with = guild_with_channel
_bot = bot_for_guild


@pytest.mark.asyncio
async def test_allowed_channel_id_is_processed_exactly_once(deps, spies):
    channel = FakeChannel(42)
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [42]
    message = _message(channel, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_awaited_once_with(message, deps)
    spies.dm.assert_not_awaited()
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_channel_id_in_allowlist_is_processed(deps, spies):
    channel = FakeChannel(42)
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [17, 42, "99"]
    message = _message(channel, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_awaited_once_with(message, deps)
    spies.dm.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_id_absent_from_allowlist_is_ignored_and_sends_nothing(deps, spies):
    channel = FakeChannel(42)
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [17, 99]
    message = _message(channel, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_not_awaited()
    spies.dm.assert_not_awaited()
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_channel_id_list_takes_precedence_over_matching_name(deps, spies):
    channel = FakeChannel(42, name="allowed")
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNELS"] = ["allowed"]
    deps["ALLOWED_CHANNEL_IDS"] = [999]
    message = _message(channel, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_not_awaited()
    spies.dm.assert_not_awaited()
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_guild_channel_message_without_mention_is_ignored(deps, spies):
    channel = FakeChannel(42)
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [42]
    message = _message(channel, mentions=[], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_not_awaited()
    spies.dm.assert_not_awaited()
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_dm_is_processed_regardless_of_channel_allowlists(deps, spies):
    channel = FakeDMChannel(7)
    guild = FakeGuild(1)
    bot = _bot(guild)
    deps["ALLOWED_CHANNELS"] = ["somewhere-else"]
    deps["ALLOWED_CHANNEL_IDS"] = [999]
    message = _message(channel, guild=None)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.dm.assert_awaited_once_with(message, deps)
    spies.channel.assert_not_awaited()
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_thread_whose_parent_is_allowed_is_processed(deps, spies):
    parent = FakeChannel(10, name="parent")
    guild = _guild_with(parent)
    thread = FakeThread(500, parent)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [10]
    message = _message(thread, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_awaited_once_with(message, deps)
    spies.dm.assert_not_awaited()
    assert thread.sent_messages == []


@pytest.mark.asyncio
async def test_thread_whose_parent_is_not_allowed_is_ignored(deps, spies):
    parent = FakeChannel(99, name="parent")
    guild = _guild_with(parent)
    # The thread's own ID is allowlisted; only its parent is not.
    thread = FakeThread(10, parent)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [10]
    message = _message(thread, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_not_awaited()
    spies.dm.assert_not_awaited()
    assert thread.sent_messages == []


@pytest.mark.asyncio
async def test_thread_without_parent_object_uses_an_allowlisted_parent_id(deps, spies):
    parent = FakeChannel(10, name="parent")
    guild = _guild_with(parent)
    thread = FakeThread(500, parent)
    thread.parent = None
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [10]
    message = _message(thread, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_awaited_once_with(message, deps)
    spies.dm.assert_not_awaited()
    assert thread.sent_messages == []


@pytest.mark.asyncio
async def test_thread_without_parent_object_rejects_an_unlisted_parent_id(deps, spies):
    parent = FakeChannel(99, name="parent")
    guild = _guild_with(parent)
    thread = FakeThread(10, parent)
    thread.parent = None
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [10]
    message = _message(thread, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_not_awaited()
    spies.dm.assert_not_awaited()
    assert thread.sent_messages == []


@pytest.mark.asyncio
async def test_message_from_another_bot_is_processed(deps, spies):
    channel = FakeChannel(42)
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [42]
    other_bot = FakeUser(999, bot=True)
    message = _message(channel, author=other_bot, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_awaited_once_with(message, deps)
    spies.dm.assert_not_awaited()
    assert channel.sent_messages == []
