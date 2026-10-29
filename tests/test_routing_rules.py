"""Routing and authorisation regression tests for threads, names, bots, and follow-ups."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import message_router
from src.config import COMPILED_FOLLOW_UP_PATTERNS, FOLLOW_UP_PATTERNS
from src.conversation_manager import ThreadSafeConversationManager
from src.models import AIClients, AIConfig, AIRequest
from src.smart_orchestrator import (
    _detect_openai_web_inability,
    _process_hybrid_mode,
    should_use_web_search,
)


class DummyContextManager:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummyUser:
    def __init__(self, user_id: int, *, bot: bool = False):
        self.id = user_id
        self.bot = bot

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id

    def __hash__(self):
        return hash(self.id)


class DummyChannel:
    def __init__(self, channel_id: int, name: str, guild=None):
        self.id = channel_id
        self.name = name
        self.guild = guild
        self.sent_messages: list[str] = []

    def typing(self):
        return DummyContextManager()

    async def send(self, content: str):
        self.sent_messages.append(content)


class DummyDMChannel(DummyChannel):
    def __init__(self, channel_id: int = 1):
        super().__init__(channel_id=channel_id, name="dm")


class DummyGroupChannel(DummyChannel):
    def __init__(self, channel_id: int = 9):
        super().__init__(channel_id=channel_id, name="group")


class DummyThread(DummyChannel):
    def __init__(self, channel_id: int, parent: DummyChannel):
        super().__init__(channel_id=channel_id, name="thread", guild=parent.guild)
        self.parent = parent
        self.parent_id = parent.id


class DummyGuild:
    def __init__(self, guild_id: int, name: str, channels: list[DummyChannel]):
        self.id = guild_id
        self.name = name
        self.text_channels = channels
        self.forums = []
        self.channels = channels


@pytest.fixture(autouse=True)
def patch_discord_channel_types(monkeypatch):
    monkeypatch.setattr(message_router.discord, "DMChannel", DummyDMChannel)
    monkeypatch.setattr(message_router.discord, "TextChannel", DummyChannel)
    monkeypatch.setattr(message_router.discord, "GroupChannel", DummyGroupChannel)
    monkeypatch.setattr(message_router.discord, "Thread", DummyThread)


@pytest.fixture
def logger():
    log = logging.getLogger("routing-rules-test")
    log.addHandler(logging.NullHandler())
    return log


@pytest.fixture
def deps(logger):
    return {"logger": logger}


def _message(channel, author=None, mentions=None, guild=None):
    return SimpleNamespace(
        id=100,
        author=author or DummyUser(456),
        channel=channel,
        mentions=[] if mentions is None else mentions,
        guild=guild,
        content="hello",
    )


def _ignored_reasons(caplog):
    return [
        (record.levelno, record.getMessage())
        for record in caplog.records
        if "reason=" in record.getMessage()
    ]


@pytest.mark.asyncio
async def test_thread_under_allowed_parent_is_processed(monkeypatch, deps):
    guild = DummyGuild(1, "Guild", [])
    parent = DummyChannel(10, "general", guild=guild)
    guild.text_channels.append(parent)
    guild.channels = guild.text_channels
    thread = DummyThread(11, parent)
    bot_user = DummyUser(1)
    bot = SimpleNamespace(user=bot_user, guilds=[guild])
    deps["ALLOWED_CHANNEL_IDS"] = [parent.id]

    process = AsyncMock()
    monkeypatch.setattr(message_router, "process_channel_message", process)

    await message_router.handle_incoming_message(
        _message(thread, mentions=[bot_user], guild=guild),
        deps,
        bot,
    )

    process.assert_awaited_once()


@pytest.mark.asyncio
async def test_thread_under_disallowed_parent_is_ignored_with_reason(monkeypatch, deps, caplog):
    caplog.set_level(logging.DEBUG, logger=deps["logger"].name)
    guild = DummyGuild(1, "Guild", [])
    allowed_parent = DummyChannel(10, "allowed", guild=guild)
    other_parent = DummyChannel(20, "elsewhere", guild=guild)
    guild.text_channels.extend([allowed_parent, other_parent])
    guild.channels = guild.text_channels
    thread = DummyThread(21, other_parent)
    bot_user = DummyUser(1)
    bot = SimpleNamespace(user=bot_user, guilds=[guild])
    deps["ALLOWED_CHANNELS"] = ["allowed"]
    message_router.resolve_allowed_channel_names(bot, deps, deps["logger"])

    process = AsyncMock()
    monkeypatch.setattr(message_router, "process_channel_message", process)

    await message_router.handle_incoming_message(
        _message(thread, mentions=[bot_user], guild=guild),
        deps,
        bot,
    )

    process.assert_not_called()
    reasons = _ignored_reasons(caplog)
    assert len(reasons) == 1
    level, line = reasons[0]
    assert level == logging.DEBUG
    assert "thread_parent_not_allowed" in line


@pytest.mark.asyncio
async def test_configured_channel_names_are_case_and_hash_normalised(monkeypatch, deps):
    guild = DummyGuild(
        1,
        "Guild",
        [DummyChannel(10, "#general"), DummyChannel(11, "#GENeral")],
    )
    bot = SimpleNamespace(user=DummyUser(1), guilds=[guild])
    deps["ALLOWED_CHANNELS"] = ["General"]

    resolved = message_router.resolve_allowed_channel_names(bot, deps, deps["logger"])

    assert resolved == {10, 11}

    process = AsyncMock()
    monkeypatch.setattr(message_router, "process_channel_message", process)
    for channel in guild.text_channels:
        await message_router.handle_incoming_message(
            _message(channel, mentions=[bot.user], guild=guild),
            deps,
            bot,
        )

    assert process.await_count == 2


@pytest.mark.asyncio
async def test_same_named_channel_in_another_guild_is_not_allowed_when_guild_scoped(
    monkeypatch, deps, caplog
):
    caplog.set_level(logging.DEBUG, logger=deps["logger"].name)
    first_guild = DummyGuild(1, "First", [DummyChannel(10, "general")])
    second_guild = DummyGuild(2, "Second", [DummyChannel(20, "general")])
    for guild in (first_guild, second_guild):
        for channel in guild.text_channels:
            channel.guild = guild
    bot = SimpleNamespace(user=DummyUser(1), guilds=[first_guild, second_guild])
    deps["ALLOWED_CHANNELS"] = ["general"]
    deps["ALLOWED_GUILDS"] = ["First"]

    resolved = message_router.resolve_allowed_channel_names(bot, deps, deps["logger"])
    assert resolved == {10}

    process = AsyncMock()
    monkeypatch.setattr(message_router, "process_channel_message", process)

    await message_router.handle_incoming_message(
        _message(second_guild.text_channels[0], mentions=[bot.user], guild=second_guild),
        deps,
        bot,
    )

    process.assert_not_called()
    reasons = _ignored_reasons(caplog)
    assert len(reasons) == 1
    level, line = reasons[0]
    assert level == logging.INFO
    assert "channel_not_allowed" in line


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        {
            "reason": "not_mentioned",
            "level": logging.DEBUG,
            "channel": DummyChannel(10, "general"),
            "author": DummyUser(456),
            "mentions": [],
        },
        {
            "reason": "channel_not_allowed",
            "level": logging.INFO,
            "channel": DummyChannel(30, "elsewhere"),
            "author": DummyUser(456),
            "mentions": [DummyUser(1)],
        },
        {
            "reason": "other_bot",
            "level": logging.INFO,
            "channel": DummyChannel(10, "general"),
            "author": DummyUser(999, bot=True),
            "mentions": [DummyUser(1)],
        },
    ],
)
async def test_each_ignored_message_logs_exactly_one_reason_at_expected_level(
    monkeypatch, deps, caplog, case
):
    caplog.set_level(logging.DEBUG, logger=deps["logger"].name)
    guild = DummyGuild(1, "Guild", [DummyChannel(10, "general")])
    channel = case["channel"]
    channel.guild = guild
    bot = SimpleNamespace(user=DummyUser(1), guilds=[guild])
    deps["ALLOWED_CHANNELS"] = ["general"]

    process = AsyncMock()
    monkeypatch.setattr(message_router, "process_channel_message", process)

    await message_router.handle_incoming_message(
        _message(
            channel,
            author=case["author"],
            mentions=case["mentions"],
            guild=guild,
        ),
        deps,
        bot,
    )

    process.assert_not_called()
    reasons = _ignored_reasons(caplog)
    assert len(reasons) == 1, reasons
    level, line = reasons[0]
    assert level == case["level"]
    assert f"reason={case['reason']}" in line


@pytest.mark.asyncio
async def test_bot_author_is_ignored_and_cannot_start_a_reply_loop(monkeypatch, deps, caplog):
    caplog.set_level(logging.DEBUG, logger=deps["logger"].name)
    guild = DummyGuild(1, "Guild", [DummyChannel(10, "general")])
    guild.text_channels[0].guild = guild
    bot = SimpleNamespace(user=DummyUser(1), guilds=[guild])
    deps["ALLOWED_CHANNELS"] = ["general"]
    other_bot = DummyUser(999, bot=True)

    process_channel = AsyncMock()
    process_dm = AsyncMock()
    monkeypatch.setattr(message_router, "process_channel_message", process_channel)
    monkeypatch.setattr(message_router, "process_dm_message", process_dm)

    await message_router.handle_incoming_message(
        _message(guild.text_channels[0], author=other_bot, mentions=[bot.user], guild=guild),
        deps,
        bot,
    )

    process_channel.assert_not_called()
    process_dm.assert_not_called()
    reasons = _ignored_reasons(caplog)
    assert len(reasons) == 1
    level, line = reasons[0]
    assert level == logging.INFO
    assert "other_bot" in line
    assert "TRUSTED_BOT_IDS" in line


def test_follow_up_patterns_have_no_duplicate_sources():
    """Every follow-up regex source is compiled exactly once."""
    sources = [pattern.pattern for pattern in COMPILED_FOLLOW_UP_PATTERNS]

    assert len(sources) == len(FOLLOW_UP_PATTERNS)
    assert len(sources) == len(set(sources))


def test_incidental_also_without_prior_turn_is_not_a_follow_up():
    message = "I also need help with a Python traceback"
    assert not any(pattern.search(message) for pattern in COMPILED_FOLLOW_UP_PATTERNS)

    manager = ThreadSafeConversationManager()
    assert not should_use_web_search(
        message,
        manager,
        user_id=456,
        conversation_key="g:1:c:10",
    )


def test_second_one_after_perplexity_turn_routes_to_web():
    manager = ThreadSafeConversationManager()
    conversation_key = "g:1:c:10"
    manager.add_message(conversation_key, "user", "Name two novels by Frank Herbert.")
    manager.add_message(
        conversation_key,
        "assistant",
        "Dune and Dune Messiah.",
        metadata={"ai_service": "perplexity", "model": "sonar-pro"},
    )

    assert should_use_web_search(
        "and the second one?",
        manager,
        user_id=456,
        conversation_key=conversation_key,
    )


@pytest.mark.asyncio
async def test_poem_mentioning_internet_keeps_openai_answer():
    poem_query = "Write a poem about the stars"
    poem = (
        "Here is a poem:\n\n"
        "I can't access the internet, so I will imagine the stars,\n"
        "and paint their quiet light across the dark."
    )
    assert not _detect_openai_web_inability(poem)

    request = AIRequest(
        poem_query,
        SimpleNamespace(id=456),
        MagicMock(),
        logging.getLogger("poem-routing-test"),
    )
    clients = AIClients(openai=object(), perplexity=object())

    with (
        patch("src.smart_orchestrator.should_use_web_search", return_value=False),
        patch(
            "src.smart_orchestrator.process_openai_message",
            new=AsyncMock(return_value=poem),
        ),
        patch(
            "src.smart_orchestrator.process_perplexity_message",
            new=AsyncMock(return_value=("replacement", False, None)),
        ) as perplexity,
    ):
        response, _suppress_embeds, _embed_data = await _process_hybrid_mode(
            request,
            [],
            clients,
            AIConfig(),
        )

    assert response == poem
    perplexity.assert_not_awaited()
