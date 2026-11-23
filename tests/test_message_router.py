import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import message_router
from tests.helpers import FakeChannel, FakeDMChannel, FakeUser

pytestmark = pytest.mark.usefixtures("fake_discord_types")


class DummyFailingChannel(FakeDMChannel):
    def __init__(self, channel_id: int = 3):
        super().__init__(channel_id=channel_id)
        self.send_attempts = 0

    async def send(self, _content: str):
        self.send_attempts += 1
        message = "send failed"
        raise RuntimeError(message)


@pytest.fixture
def deps():
    logger = logging.getLogger("router-test")
    logger.addHandler(logging.NullHandler())
    return {"logger": logger, "ALLOWED_CHANNELS": ["allowed"]}


@pytest.mark.asyncio
async def test_ignores_self_message(monkeypatch, deps):
    bot_user = FakeUser(1)
    bot = SimpleNamespace(user=bot_user)
    channel = FakeChannel(2, "allowed")
    message = SimpleNamespace(
        author=bot_user,
        channel=channel,
        mentions=[bot_user],
        guild=None,
    )

    dm_mock = AsyncMock()
    ch_mock = AsyncMock()
    monkeypatch.setattr(message_router, "process_dm_message", dm_mock)
    monkeypatch.setattr(message_router, "process_channel_message", ch_mock)

    await message_router.handle_incoming_message(message, deps, bot)

    dm_mock.assert_not_called()
    ch_mock.assert_not_called()
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_routes_dm_message(monkeypatch, deps):
    bot = SimpleNamespace(user=object())
    channel = FakeDMChannel(1)
    author = SimpleNamespace(id=123)
    message = SimpleNamespace(
        author=author,
        channel=channel,
        mentions=[],
        guild=None,
    )

    dm_mock = AsyncMock()
    monkeypatch.setattr(message_router, "process_dm_message", dm_mock)

    await message_router.handle_incoming_message(message, deps, bot)

    dm_mock.assert_awaited_once_with(message, deps)
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_routes_channel_message(monkeypatch, deps):
    bot_user = FakeUser(1)
    bot = SimpleNamespace(user=bot_user)
    channel = FakeChannel(2, "allowed")
    author = FakeUser(456)
    message = SimpleNamespace(
        author=author,
        channel=channel,
        mentions=[bot_user],
        guild=SimpleNamespace(id=999, name="guild"),
    )

    ch_mock = AsyncMock()
    dm_mock = AsyncMock()
    monkeypatch.setattr(message_router, "process_channel_message", ch_mock)
    monkeypatch.setattr(message_router, "process_dm_message", dm_mock)

    await message_router.handle_incoming_message(message, deps, bot)

    ch_mock.assert_awaited_once_with(message, deps)
    dm_mock.assert_not_called()
    assert channel.sent_messages == []


@pytest.mark.asyncio
async def test_notifies_on_processing_error(monkeypatch, deps):
    bot = SimpleNamespace(user=object())
    channel = FakeDMChannel(1)
    author = SimpleNamespace(id=789)
    message = SimpleNamespace(
        author=author,
        channel=channel,
        mentions=[],
        guild=None,
    )

    dm_mock = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(message_router, "process_dm_message", dm_mock)

    await message_router.handle_incoming_message(message, deps, bot)

    assert [content for content, _kwargs in channel.sent_messages] == [
        "🔧 An unexpected error occurred. The issue has been logged."
    ]


@pytest.mark.asyncio
async def test_send_failure_is_swallowed(monkeypatch, deps):
    bot = SimpleNamespace(user=object())
    channel = DummyFailingChannel()
    author = SimpleNamespace(id=321)
    message = SimpleNamespace(
        author=author,
        channel=channel,
        mentions=[],
        guild=None,
    )

    dm_mock = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(message_router, "process_dm_message", dm_mock)

    await message_router.handle_incoming_message(message, deps, bot)

    # Even though sending fails, the error is swallowed and no exception is propagated.
    assert channel.send_attempts == 1
