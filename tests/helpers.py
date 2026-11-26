"""
Shared test utilities for DiscordianAI tests.

This module contains common fake classes and helper functions used across
multiple test files to eliminate duplication and maintain DRY principles.
"""

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp.test_utils
import discord
import openai


class FakeTyping:
    """Minimal async typing context manager for Discord doubles."""

    async def __aenter__(self):
        """Enter the typing context."""

    async def __aexit__(self, exc_type, exc, tb):
        """Leave the typing context without suppressing exceptions."""
        return False


class FakeUser:
    """Discord user double with id-based equality."""

    def __init__(self, user_id: int, *, bot: bool = False, name: str | None = None):
        """Create a user with a stable synthetic id."""
        self.id = user_id
        self.bot = bot
        self.name = name or f"user-{user_id}"
        self.mention = f"<@{user_id}>"

    def __eq__(self, other):
        """Compare users by id, as Discord objects do."""
        return getattr(other, "id", None) == self.id

    def __hash__(self):
        """Hash by id so users can be set members."""
        return hash(self.id)


class FakeGuild:
    """Discord guild double with text channels and forums."""

    def __init__(self, guild_id: int, name: str = "Guild", channels=None):
        """Create a guild, optionally seeded with channels."""
        self.id = guild_id
        self.name = name
        self.text_channels = list(channels or [])
        self.forums: list = []
        self.channels = self.text_channels


class FakeChannel:
    """Discord channel double that records sends."""

    def __init__(self, channel_id: int, name: str = "general", guild=None):
        """Create a channel bound to an optional guild."""
        self.id = channel_id
        self.name = name
        self.guild = guild
        self.sent_messages: list[tuple[str, dict]] = []

    def typing(self):
        """Return an async typing context manager."""
        return FakeTyping()

    async def send(self, content: str, **kwargs):
        """Record one outgoing message."""
        self.sent_messages.append((content, kwargs))


class FakeDMChannel(FakeChannel):
    """Direct-message channel double."""

    def __init__(self, channel_id: int = 1, guild=None):
        """Create a DM channel."""
        super().__init__(channel_id, "dm", guild)


class FakeGroupChannel(FakeChannel):
    """Group direct-message channel double."""

    def __init__(self, channel_id: int = 2, guild=None):
        """Create a group DM channel."""
        super().__init__(channel_id, "group", guild)


class FakeThread(FakeChannel):
    """Thread double that points at its parent channel."""

    def __init__(self, channel_id: int, parent: FakeChannel):
        """Create a thread under ``parent``."""
        super().__init__(channel_id, "thread", parent.guild)
        self.parent = parent
        self.parent_id = parent.id


class FakeMessage:
    """Discord message double that records replies."""

    def __init__(  # noqa: PLR0913 - mirrors the Discord message fields
        self,
        *,
        message_id: int = 100,
        author=None,
        channel=None,
        guild=None,
        mentions=None,
        content: str = "hello",
    ):
        """Create a message with optional author, channel, and mentions."""
        self.id = message_id
        self.author = author or FakeUser(42)
        self.channel = channel
        self.guild = guild
        self.mentions = list(mentions or [])
        self.content = content
        self.replies: list[tuple[str, dict]] = []

    def to_reference(self, *, fail_if_not_exists: bool = True, **_kwargs):
        """Build the reply reference Discord uses to target this message."""
        channel_id = getattr(self.channel, "id", None)
        return discord.MessageReference(
            message_id=self.id,
            channel_id=int(channel_id) if channel_id is not None else 0,
            fail_if_not_exists=fail_if_not_exists,
        )

    async def reply(self, content: str, **kwargs):
        """Record one reply."""
        self.replies.append((content, kwargs))


def make_router_message(channel, *, author=None, mentions=None, guild=None, content="hello"):
    """Build a router-shaped message for the real handle_incoming_message."""
    return SimpleNamespace(
        id=100,
        author=author or FakeUser(42),
        channel=channel,
        mentions=list(mentions or []),
        guild=guild,
        content=content,
    )


def guild_with_channel(channel: FakeChannel) -> FakeGuild:
    """Create a guild whose text channels contain ``channel``."""
    guild = FakeGuild(1, channels=[channel])
    channel.guild = guild
    return guild


def bot_for_guild(guild: FakeGuild):
    """Return a bot double whose user is synthetic id 1."""
    return SimpleNamespace(user=FakeUser(1, bot=True), guilds=[guild])


class FakeBreaker:
    """Minimal circuit-breaker snapshot provider for health tests."""

    def __init__(self, last_success_time: float):
        """Create a closed breaker with the supplied last success time."""
        self._last_success_time = last_success_time

    def snapshot(self) -> dict:
        """Return a closed breaker snapshot."""
        return {
            "state": "CLOSED",
            "consecutive_failures": 0,
            "last_failure_time": 0.0,
            "last_success_time": self._last_success_time,
        }


class HealthTestResponse:
    """Response double exposing the attributes health tests assert on."""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def json(self):
        """Decode and return the JSON body."""
        return json.loads(self.text)


def request_health(app, path: str) -> HealthTestResponse:
    """GET a health path through aiohttp's in-process test server."""

    async def _request() -> HealthTestResponse:
        async with aiohttp.test_utils.TestClient(
            aiohttp.test_utils.TestServer(app),
        ) as client:
            response = await client.get(path)
            return HealthTestResponse(response.status, await response.text())

    return asyncio.run(_request())


class FakeAppRunner:
    """Minimal aiohttp AppRunner double with injectable failures."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.setup_calls = 0
        self.cleanup_calls = 0
        self.setup_error: BaseException | None = None
        self.cleanup_error: Exception | None = None
        self._addresses: list[tuple[str, int]] = [("127.0.0.1", 0)]

    @property
    def addresses(self) -> list[tuple[str, int]]:
        """Return the listening addresses, empty when no site bound."""
        return list(self._addresses)

    def report_no_listener(self) -> None:
        """Pretend no site ever bound a listening socket."""
        self._addresses = []

    async def setup(self) -> None:
        """Register the runner, or raise the configured startup failure."""
        self.setup_calls += 1
        if self.setup_error is not None:
            raise self.setup_error

    async def cleanup(self) -> None:
        """Release the runner, or raise the configured shutdown failure."""
        self.cleanup_calls += 1
        if self.cleanup_error is not None:
            raise self.cleanup_error


class FakeSite:
    """Minimal aiohttp TCPSite double with injectable failures."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.start_error: BaseException | None = None
        self.stop_error: Exception | None = None

    async def start(self) -> None:
        """Bind the site, or raise the configured startup failure."""
        self.start_calls += 1
        if self.start_error is not None:
            raise self.start_error

    async def stop(self) -> None:
        """Unbind the site, or raise the configured shutdown failure."""
        self.stop_calls += 1
        if self.stop_error is not None:
            raise self.stop_error


def health_deps(  # noqa: PLR0913 - one keyword per health fixture knob
    *,
    connected=True,
    has_openai=True,
    has_perplexity=True,
    latency=0.05,
    guilds=None,
    config=None,
    breakers=None,
    pool_manager=None,
):
    """Create dependency data for the health HTTP app."""
    bot = MagicMock()
    bot.is_ready.return_value = connected
    bot.guilds = [MagicMock(), MagicMock()] if guilds is None else guilds
    bot.latency = latency

    settings = {
        "OPENAI_API_KEY": "sk-test-key" if has_openai else None,
        "PERPLEXITY_API_KEY": "pplx-test-key" if has_perplexity else None,
        "GPT_MODEL": "gpt-5-mini",
        "PERPLEXITY_MODEL": "perplexity/sonar",
        "HEALTH_ENABLED": True,
    }
    settings.update(config or {})

    deps = {
        "bot": bot,
        "client": MagicMock() if has_openai else None,
        "perplexity_client": MagicMock() if has_perplexity else None,
        "config": settings,
    }
    if breakers is not None:
        deps["circuit_breakers"] = breakers
    if pool_manager is not None:
        deps["connection_pool_manager"] = pool_manager
    return deps


def config_env_keys() -> set[str]:
    """Return every environment key the config loader reads."""
    from src.config import _CONFIG_DEFAULTS

    source = Path(__file__).resolve().parents[1] / "src" / "config.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_apply_env_overrides":
            continue
        for statement in node.body:
            if not isinstance(statement, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "env_keys"
                for target in statement.targets
            ):
                continue
            return set(_CONFIG_DEFAULTS) | set(ast.literal_eval(statement.value))
    msg = "Could not find env_keys in src/config.py"
    raise AssertionError(msg)


def _search_results_for(citations: list[str]) -> list[dict[str, str]]:
    """Build live-shaped search results for fake Perplexity responses."""
    return [
        {
            "title": f"Source {index}",
            "url": url,
            "date": "2026-10-27",
            "last_updated": "2026-10-28",
            "snippet": f"Snippet for source {index}",
            "source": "web",
        }
        for index, url in enumerate(citations, 1)
    ]


class FakeResponse:
    """Fake response object for API testing."""

    def __init__(self, content="Test response", citations=None, search_results=None):
        self.choices = [FakeChoice(content)]
        output_search_results = search_results
        if output_search_results is None and citations:
            output_search_results = _search_results_for(citations)
        self.output = []
        if output_search_results:
            self.output.append({"type": "search_results", "results": output_search_results})
        self.output.append(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content or ""}],
            }
        )
        if citations is not None:
            self.citations = citations
        if search_results is not None:
            self.search_results = search_results


class FakeChoice:
    """Fake choice object for API testing."""

    def __init__(self, content):
        self.message = _FakeResponseMessage(content)


class _FakeResponseMessage:
    """Response message payload for the API fakes above."""

    def __init__(self, content):
        self.content = content


class FakeOpenAIClient:
    """Fake OpenAI client for testing."""

    def __init__(self, response_text="Test response", should_raise=False, return_none=False):
        self.response_text = response_text
        self.should_raise = should_raise
        self.return_none = return_none
        self.chat = self.Chat(self)

    class Chat:
        def __init__(self, client):
            self.client = client
            self.completions = self.Completions(client)

        class Completions:
            def __init__(self, client):
                self.client = client

            async def create(self, *_args, **_kwargs):
                if self.client.should_raise:
                    msg = "Test exception"
                    raise Exception(msg)
                if self.client.return_none:
                    return FakeResponse("")
                return FakeResponse(self.client.response_text)


class FakePerplexityClient:
    """Fake Perplexity client for testing."""

    def __init__(self, response_text="Test response", citations=None, search_results=None):
        self.response_text = response_text
        self.citations = citations or []
        if search_results is None:
            search_results = _search_results_for(self.citations)
        self.search_results = search_results
        self.chat = self.Chat(self)
        self.responses = self.Responses(self)

    class Chat:
        def __init__(self, client):
            self.client = client
            self.completions = self.Completions(client)

        class Completions:
            def __init__(self, client):
                self.client = client

            async def create(self, *_args, **_kwargs):
                return FakeResponse(
                    self.client.response_text,
                    citations=self.client.citations,
                    search_results=self.client.search_results,
                )

    class Responses:
        def __init__(self, client):
            self.client = client

        async def create(self, *_args, **_kwargs):
            return FakeResponse(
                self.client.response_text,
                citations=self.client.citations,
                search_results=self.client.search_results,
            )


def create_mock_user(user_id=12345, username="testuser", display_name="Test User"):
    """Create a mock Discord user for testing."""
    user = AsyncMock()
    user.id = user_id
    user.name = username
    user.display_name = display_name
    user.mention = f"<@{user_id}>"
    return user


def create_mock_channel(channel_id=67890, name="test-channel"):
    """Create a mock Discord channel for testing."""
    channel = AsyncMock()
    channel.id = channel_id
    channel.name = name
    channel.mention = f"<#{channel_id}>"
    return channel


def create_mock_message(content="test message", user=None, channel=None):
    """Create a mock Discord message for testing."""
    message = AsyncMock()
    message.content = content
    message.author = user or create_mock_user()
    message.channel = channel or create_mock_channel()
    message.mentions = []
    message.embeds = []
    return message


def create_test_context(user_id=12345, username="testuser", display_name="Test User"):
    """Create a complete test context with user, conversation manager, and logger."""
    from unittest.mock import MagicMock

    from src.conversation_manager import ThreadSafeConversationManager

    user = create_mock_user(user_id, username, display_name)
    conversation_manager = ThreadSafeConversationManager()
    logger = MagicMock()

    return {"user": user, "conversation_manager": conversation_manager, "logger": logger}


def create_openai_response(content="Test response from OpenAI", finish_reason="stop"):
    """Create a mock OpenAI API response."""
    from unittest.mock import Mock

    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = content
    mock_response.choices[0].finish_reason = finish_reason
    mock_response.id = "chatcmpl-test123"
    mock_response.usage = Mock()
    mock_response.usage.prompt_tokens = 25
    mock_response.usage.completion_tokens = 15
    mock_response.usage.total_tokens = 40

    return mock_response


def create_perplexity_response(
    content="Test response from Perplexity", citations=None, search_results=None
):
    """Create a mock Perplexity API response."""
    from unittest.mock import Mock

    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = content
    mock_response.choices[0].finish_reason = "stop"
    mock_response.id = "pplx-test123"
    mock_response.usage = Mock()
    mock_response.usage.prompt_tokens = 30
    mock_response.usage.completion_tokens = 20
    mock_response.usage.total_tokens = 50

    if citations:
        mock_response.citations = citations
    if search_results is None:
        search_results = _search_results_for(citations or [])
    mock_response.search_results = search_results

    return mock_response


# Common test data constants
TEST_USER_IDS = [12345, 67890, 99999, 11111, 22222]
TEST_MESSAGES = [
    "Hello, how are you?",
    "What's the weather like?",
    "Tell me about artificial intelligence",
    "Write a poem about cats",
    "What's happening in the news today?",
]
TEST_RESPONSES = {
    "openai": "This is a test response from OpenAI",
    "perplexity": "This is a test response from Perplexity [1]",
    "hybrid": "This is a hybrid response combining both sources",
}

PROVIDER_BODY_MARKER = "BODY-MARKER-XYZ"


def provider_status_error(body_marker: str = PROVIDER_BODY_MARKER):
    """Build an SDK status error whose message carries a fake response body."""
    response = SimpleNamespace(status_code=500, headers={}, request=SimpleNamespace())
    return openai.InternalServerError(
        body_marker,
        response=response,
        body={"error": {"message": body_marker}},
    )


def assert_no_provider_body_in_logs(caplog, marker: str = PROVIDER_BODY_MARKER) -> None:
    """Assert no captured record carries ``marker`` in message, args, or traceback."""
    leaked = []
    for record in caplog.records:
        payloads = (record.getMessage(), repr(record.args), record.exc_text or "")
        if any(marker in payload for payload in payloads):
            leaked.append(payloads)
    assert not leaked, f"provider body leaked into log records: {leaked}"
