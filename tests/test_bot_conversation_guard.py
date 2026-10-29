"""Bot-authored conversations: answered, never mentioned, and capped."""

from dataclasses import dataclass, field
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import message_router
from src.config import _CONFIG_DEFAULTS, load_config
from src.conversation_manager import (
    ThreadSafeConversationManager,
    conversation_key_for_message,
)
from src.rate_limits import RateLimiter

BOT_ID = 1
OTHER_BOT_ID = 999
HUMAN_ID = 42
CHANNEL_ID = 5
GUILD_ID = 1
RESPONSE = "A deterministic answer."

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeUser:
    def __init__(self, user_id: int, *, bot: bool = False, name: str | None = None):
        self.id = user_id
        self.bot = bot
        self.name = name or f"user-{user_id}"
        self.mention = f"<@{user_id}>"

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id

    def __hash__(self):
        return hash(self.id)


class FakeGuild:
    def __init__(self, guild_id: int, name: str = "Guild"):
        self.id = guild_id
        self.name = name
        self.text_channels: list[FakeChannel] = []
        self.forums: list[FakeChannel] = []
        self.channels = self.text_channels


class FakeChannel:
    def __init__(self, channel_id: int, name: str, guild: FakeGuild):
        self.id = channel_id
        self.name = name
        self.guild = guild
        self.sent_messages: list[tuple[str, dict]] = []

    def typing(self):
        return FakeTyping()

    async def send(self, content: str, **kwargs):
        self.sent_messages.append((content, kwargs))


class FakeDMChannel(FakeChannel):
    def __init__(self, channel_id: int = 7):
        super().__init__(channel_id, "dm", FakeGuild(0))


class FakeGroupChannel(FakeChannel):
    def __init__(self, channel_id: int = 8):
        super().__init__(channel_id, "group", FakeGuild(0))


class FakeThread(FakeChannel):
    def __init__(self, channel_id: int, parent: FakeChannel):
        super().__init__(channel_id, "thread", parent.guild)
        self.parent = parent
        self.parent_id = parent.id


@dataclass
class FakeMessage:
    id: int
    author: FakeUser
    channel: FakeChannel
    guild: FakeGuild
    mentions: list[FakeUser]
    content: str
    replies: list[tuple[str, dict]] = field(default_factory=list)

    async def reply(self, content: str, **kwargs):
        self.replies.append((content, kwargs))


@pytest.fixture(autouse=True)
def fake_discord_types(monkeypatch):
    monkeypatch.setattr(message_router.discord, "DMChannel", FakeDMChannel)
    monkeypatch.setattr(message_router.discord, "TextChannel", FakeChannel)
    monkeypatch.setattr(message_router.discord, "GroupChannel", FakeGroupChannel)
    monkeypatch.setattr(message_router.discord, "Thread", FakeThread)


class Harness:
    """Run real routing, processing, orchestration, and delivery for one channel."""

    def __init__(self, openai_response):
        self.guild = FakeGuild(GUILD_ID)
        self.channel = FakeChannel(CHANNEL_ID, "general", self.guild)
        self.guild.text_channels.append(self.channel)
        self.guild.channels = self.guild.text_channels
        self.bot_user = FakeUser(BOT_ID, bot=True, name="DiscordianAI")
        self.bot = SimpleNamespace(user=self.bot_user, guilds=[self.guild])
        self.other_bot = FakeUser(OTHER_BOT_ID, bot=True, name="HelperBot")
        self.human = FakeUser(HUMAN_ID, name="Human")
        self.create = AsyncMock(return_value=openai_response(RESPONSE))
        self.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
        )
        self.manager = ThreadSafeConversationManager()
        self.logger = logging.getLogger("bot-conversation-guard-test")
        self.logger.addHandler(logging.NullHandler())
        config = {
            "GPT_MODEL": "gpt-test",
            "PERPLEXITY_MODEL": "sonar-pro",
            "SYSTEM_MESSAGE": "system",
            "OUTPUT_TOKENS": 256,
            "PERPLEXITY_OUTPUT_TOKENS": 256,
            "INPUT_TOKENS": 10000,
            "CONTEXT_WINDOW": 128000,
            "RATE_LIMIT": 100,
            "RATE_LIMIT_PER": 60,
            "MAX_URLS_PER_MESSAGE": 3,
            "MAX_TOTAL_SCRAPED_CHARS": 1000,
            "SCRAPE_DEADLINE_SECONDS": 10.0,
            "MAX_HISTORY_PER_USER": 50,
            "CONVERSATION_TTL_SECONDS": 1800,
            "USER_LOCK_CLEANUP_INTERVAL": 3600,
            "LOOKBACK_MESSAGES_FOR_CONSISTENCY": 6,
            "ENTITY_DETECTION_MIN_WORDS": 10,
        }
        self.deps = {
            "logger": self.logger,
            "config": config,
            "client": self.client,
            "perplexity_client": None,
            "rate_limiter": RateLimiter(),
            "conversation_manager": self.manager,
            "RATE_LIMIT": config["RATE_LIMIT"],
            "RATE_LIMIT_PER": config["RATE_LIMIT_PER"],
            "GPT_MODEL": config["GPT_MODEL"],
            "PERPLEXITY_MODEL": config["PERPLEXITY_MODEL"],
            "SYSTEM_MESSAGE": config["SYSTEM_MESSAGE"],
            "OUTPUT_TOKENS": config["OUTPUT_TOKENS"],
            "ALLOWED_CHANNELS": [],
            "ALLOWED_CHANNEL_IDS": [self.channel.id],
            "ALLOWED_GUILDS": [],
            "ALLOWED_GUILD_IDS": [],
        }
        self._sequence = 0

    async def send(self, author: FakeUser, text: str) -> FakeMessage:
        return await self._deliver(author, text, mentions=[self.bot_user])

    async def send_unmentioned(self, author: FakeUser, text: str) -> FakeMessage:
        return await self._deliver(author, text, mentions=[])

    async def _deliver(
        self, author: FakeUser, text: str, *, mentions: list[FakeUser]
    ) -> FakeMessage:
        self._sequence += 1
        message = FakeMessage(
            id=1000 + self._sequence,
            author=author,
            channel=self.channel,
            guild=self.guild,
            mentions=mentions,
            content=f"{self.bot_user.mention} {text}" if mentions else text,
        )
        await message_router.handle_incoming_message(message, self.deps, self.bot)
        return message


@pytest.mark.asyncio
async def test_bot_mention_is_answered_without_mentioning_the_bot(openai_response):
    harness = Harness(openai_response)

    message = await harness.send(harness.other_bot, "are you there?")

    harness.create.assert_awaited_once()
    content, kwargs = message.replies[0]
    assert content == RESPONSE
    assert harness.other_bot.mention not in content
    allowed_mentions = kwargs["allowed_mentions"]
    assert allowed_mentions.users == []
    assert allowed_mentions.replied_user is False
    assert kwargs["mention_author"] is False
    assert harness.channel.sent_messages == []


@pytest.mark.asyncio
async def test_human_mention_still_carries_the_reply_prefix(openai_response):
    harness = Harness(openai_response)

    message = await harness.send(harness.human, "hello")

    harness.create.assert_awaited_once()
    content, kwargs = message.replies[0]
    assert content == f"{harness.human.mention} {RESPONSE}"
    allowed_mentions = kwargs["allowed_mentions"]
    assert allowed_mentions.users == [harness.human]
    assert allowed_mentions.replied_user is False


@pytest.mark.asyncio
async def test_third_consecutive_bot_turn_is_dropped_with_one_info_line(openai_response, caplog):
    harness = Harness(openai_response)
    await harness.send(harness.other_bot, "bot turn one")
    await harness.send(harness.other_bot, "bot turn two")

    caplog.set_level(logging.INFO, logger=harness.logger.name)
    dropped = await harness.send(harness.other_bot, "bot turn three")

    assert dropped.replies == []
    assert harness.create.await_count == 2
    guard_lines = [
        record for record in caplog.records if "consecutive_bot_streak=" in record.getMessage()
    ]
    assert len(guard_lines) == 1
    line = guard_lines[0].getMessage()
    assert guard_lines[0].levelno == logging.INFO
    assert "consecutive_bot_streak=3" in line
    assert "limit=2" in line
    assert harness.other_bot.name in line
    assert str(harness.other_bot.id) in line
    assert "human message resets the streak" in line


@pytest.mark.asyncio
async def test_human_message_resets_the_bot_streak(openai_response):
    harness = Harness(openai_response)
    await harness.send(harness.other_bot, "bot turn one")
    await harness.send(harness.other_bot, "bot turn two")
    human = await harness.send(harness.human, "a human joins")
    after_human = await harness.send(harness.other_bot, "bot turn after human")

    assert human.replies
    assert after_human.replies
    assert after_human.replies[0][0] == RESPONSE
    assert harness.create.await_count == 4


@pytest.mark.asyncio
async def test_any_human_message_resets_the_streak_even_without_a_mention(
    openai_response,
):
    harness = Harness(openai_response)
    await harness.send(harness.other_bot, "bot turn one")
    await harness.send(harness.other_bot, "bot turn two")
    human = await harness.send_unmentioned(harness.human, "a human joins")
    after_human = await harness.send(harness.other_bot, "bot turn after human")

    assert human.replies == []
    assert after_human.replies
    assert after_human.replies[0][0] == RESPONSE
    assert harness.create.await_count == 3


@pytest.mark.asyncio
async def test_dropped_bot_turn_writes_no_history_and_calls_no_provider(openai_response):
    harness = Harness(openai_response)
    first = await harness.send(harness.other_bot, "bot turn one")
    await harness.send(harness.other_bot, "bot turn two")
    conversation_key = conversation_key_for_message(first, is_dm=False)
    history_before = harness.manager.get_conversation(conversation_key=conversation_key)
    calls_before = harness.create.await_count

    dropped = await harness.send(harness.other_bot, "bot turn three")

    history_after = harness.manager.get_conversation(conversation_key=conversation_key)
    assert dropped.replies == []
    assert history_after == history_before
    assert harness.create.await_count == calls_before


def test_stale_bot_streak_is_evicted_by_the_conversation_ttl():
    class FakeClock:
        def __init__(self):
            self.now = 1000.0

        def __call__(self):
            return self.now

    clock = FakeClock()
    manager = ThreadSafeConversationManager(
        conversation_ttl_seconds=60,
        clock=clock,
    )
    key = "g:1:c:5"

    assert manager.begin_bot_turn(conversation_key=key) == (True, 1)
    assert manager.begin_bot_turn(conversation_key=key) == (True, 2)
    assert manager.begin_bot_turn(conversation_key=key) == (False, 3)

    clock.now += 61

    assert manager.begin_bot_turn(conversation_key=key) == (True, 1)


def test_trusted_bot_configuration_surface_is_gone(monkeypatch):
    for key in ("TRUSTED_BOT_IDS", "TRUSTED_BOTS"):
        monkeypatch.delenv(key, raising=False)

    config = load_config()
    assert "TRUSTED_BOT_IDS" not in config
    assert "TRUSTED_BOTS" not in config
    assert "TRUSTED_BOT_IDS" not in _CONFIG_DEFAULTS
    assert "TRUSTED_BOTS" not in _CONFIG_DEFAULTS

    sources = [
        REPO_ROOT / "src" / "config.py",
        REPO_ROOT / "config.ini.example",
        REPO_ROOT / "docs" / "Configuration.md",
        REPO_ROOT / ".env.example",
    ]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "TRUSTED_BOT_IDS" not in text, path
        assert "TRUSTED_BOTS" not in text, path
