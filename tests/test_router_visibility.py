"""Visibility tests for mentions that routing deliberately ignores."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import message_router
from tests.test_message_router_auth import (
    FakeChannel,
    FakeDMChannel,
    FakeGroupChannel,
    FakeGuild,
    FakeThread,
    FakeUser,
    _bot,
    _guild_with,
    _message,
)


@pytest.fixture(autouse=True)
def fake_discord_types(monkeypatch):
    monkeypatch.setattr(message_router.discord, "DMChannel", FakeDMChannel)
    monkeypatch.setattr(message_router.discord, "TextChannel", FakeChannel)
    monkeypatch.setattr(message_router.discord, "GroupChannel", FakeGroupChannel)
    monkeypatch.setattr(message_router.discord, "Thread", FakeThread)


@pytest.fixture
def deps():
    logger = logging.getLogger("router-visibility-test")
    logger.addHandler(logging.NullHandler())
    return {"logger": logger}


@pytest.fixture
def spies(monkeypatch):
    channel = AsyncMock()
    dm = AsyncMock()
    monkeypatch.setattr(message_router, "process_channel_message", channel)
    monkeypatch.setattr(message_router, "process_dm_message", dm)
    return SimpleNamespace(channel=channel, dm=dm)


def _info_records(caplog):
    return [record for record in caplog.records if record.levelno == logging.INFO]


@pytest.mark.asyncio
async def test_untrusted_bot_mention_logs_one_info_naming_the_author_and_setting(
    deps, spies, caplog
):
    caplog.set_level(logging.INFO, logger=deps["logger"].name)
    channel = FakeChannel(42)
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [42]
    other_bot = FakeUser(1502038480144957510, bot=True)
    message = _message(channel, author=other_bot, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    info = _info_records(caplog)
    assert len(info) == 1
    line = info[0].getMessage()
    assert "1502038480144957510" in line
    assert "TRUSTED_BOT_IDS" in line
    assert "other_bot" in line
    spies.channel.assert_not_awaited()
    spies.dm.assert_not_awaited()
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_trusted_bot_mention_is_processed_without_an_ignoring_line(deps, spies, caplog):
    caplog.set_level(logging.INFO, logger=deps["logger"].name)
    channel = FakeChannel(42)
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [42]
    other_bot = FakeUser(999, bot=True)
    deps["TRUSTED_BOT_IDS"] = [other_bot.id]
    message = _message(channel, author=other_bot, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.channel.assert_awaited_once_with(message, deps)
    spies.dm.assert_not_awaited()
    assert _info_records(caplog) == []


@pytest.mark.asyncio
async def test_mention_in_disallowed_channel_logs_one_info_with_the_reason(deps, spies, caplog):
    caplog.set_level(logging.INFO, logger=deps["logger"].name)
    channel = FakeChannel(42)
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [17, 99]
    message = _message(channel, mentions=[bot.user], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    info = _info_records(caplog)
    assert len(info) == 1
    line = info[0].getMessage()
    assert "channel_not_allowed" in line
    assert "42" in line
    spies.channel.assert_not_awaited()
    spies.dm.assert_not_awaited()
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_message_without_a_mention_logs_no_info_and_is_not_processed(deps, spies, caplog):
    caplog.set_level(logging.INFO, logger=deps["logger"].name)
    channel = FakeChannel(42)
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [42]
    message = _message(channel, mentions=[], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    assert _info_records(caplog) == []
    spies.channel.assert_not_awaited()
    spies.dm.assert_not_awaited()
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_unmentioned_bot_message_stays_at_debug(deps, spies, caplog):
    caplog.set_level(logging.DEBUG, logger=deps["logger"].name)
    channel = FakeChannel(42)
    guild = _guild_with(channel)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [42]
    other_bot = FakeUser(999, bot=True)
    message = _message(channel, author=other_bot, mentions=[], guild=guild)

    await message_router.handle_incoming_message(message, deps, bot)

    assert _info_records(caplog) == []
    assert any(
        record.levelno == logging.DEBUG and "reason=other_bot" in record.getMessage()
        for record in caplog.records
    )
    spies.channel.assert_not_awaited()
    spies.dm.assert_not_awaited()


@pytest.mark.asyncio
async def test_dm_from_a_normal_user_is_processed_without_an_ignoring_line(deps, spies, caplog):
    caplog.set_level(logging.INFO, logger=deps["logger"].name)
    channel = FakeDMChannel(7)
    guild = FakeGuild(1)
    bot = _bot(guild)
    deps["ALLOWED_CHANNEL_IDS"] = [999]
    message = _message(channel, guild=None)

    await message_router.handle_incoming_message(message, deps, bot)

    spies.dm.assert_awaited_once_with(message, deps)
    spies.channel.assert_not_awaited()
    assert _info_records(caplog) == []
