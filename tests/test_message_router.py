import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import message_router


class DummyContextManager:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummyUser:
    def __init__(self, user_id: int):
        self.id = user_id

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id


class DummyChannel:
    def __init__(self, channel_id: int):
        self.id = channel_id
        self.sent_messages: list[str] = []

    def typing(self):
        return DummyContextManager()

    async def send(self, content: str):
        self.sent_messages.append(content)


class DummyDMChannel(DummyChannel):
    def __init__(self, channel_id: int = 1):
        super().__init__(channel_id=channel_id)


class DummyTextChannel(DummyChannel):
    def __init__(self, name: str = "allowed", channel_id: int = 2):
        super().__init__(channel_id=channel_id)
        self.name = name


class DummyFailingChannel(DummyDMChannel):
    def __init__(self, channel_id: int = 3):
        super().__init__(channel_id=channel_id)
        self.send_attempts = 0

    async def send(self, content: str):
        self.send_attempts += 1
        raise RuntimeError("send failed")


@pytest.fixture(autouse=True)
def patch_discord_channel_types(monkeypatch):
    monkeypatch.setattr(message_router.discord, "DMChannel", DummyDMChannel)
    monkeypatch.setattr(message_router.discord, "TextChannel", DummyTextChannel)


@pytest.fixture()
def deps():
    logger = logging.getLogger("router-test")
    logger.addHandler(logging.NullHandler())
    return {"logger": logger, "ALLOWED_CHANNELS": ["allowed"]}


@pytest.mark.asyncio
async def test_ignores_self_message(monkeypatch, deps):
    bot_user = DummyUser(1)
    bot = SimpleNamespace(user=bot_user)
    channel = DummyTextChannel(name="allowed")
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
    channel = DummyDMChannel()
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
    bot_user = DummyUser(1)
    bot = SimpleNamespace(user=bot_user)
    channel = DummyTextChannel(name="allowed")
    author = DummyUser(456)
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
    channel = DummyDMChannel()
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

    assert channel.sent_messages == ["🔧 An unexpected error occurred. The issue has been logged."]


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
