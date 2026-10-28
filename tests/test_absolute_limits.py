"""Protocol boundaries asserted as literal numbers, not imported constants."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from src.config import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PERPLEXITY_MODEL,
    EMBED_LIMIT,
    EMBED_SAFE_LIMIT,
    MAX_SPLIT_RECURSION,
    MESSAGE_LIMIT,
)
from src.conversation_manager import ThreadSafeConversationManager
from src.discord_embeds import citation_embed_formatter
from src.health_checks import APIHealthMonitor
from src.message_splitter import send_split_message, send_split_message_with_embed
from src.models import AIClients, AIConfig, AIRequest
from src.rate_limits import RateLimiter, check_rate_limit
from src.smart_orchestrator import _process_hybrid_mode

LOGGER = logging.getLogger("absolute-limits")
LOGGER.addHandler(logging.NullHandler())
DEPS = {"logger": LOGGER}


class RecordingChannel:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def send(self, content: str, **kwargs) -> None:
        self.sent.append((content, kwargs))


def _completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop",
            )
        ],
        citations=[],
        search_results=[],
    )


def test_message_limit_is_the_discord_protocol_limit():
    assert MESSAGE_LIMIT == 2000


def test_embed_limits_are_the_discord_protocol_limits():
    assert EMBED_LIMIT == 4096
    assert EMBED_SAFE_LIMIT == 3840


@pytest.mark.asyncio
async def test_exactly_2000_characters_is_one_message():
    body = "a" * 2000
    channel = RecordingChannel()

    await send_split_message(channel, body, DEPS)

    assert len(channel.sent) == 1
    assert channel.sent[0][0] == body
    assert len(channel.sent[0][0]) <= 2000


@pytest.mark.asyncio
async def test_2001_characters_splits_into_two_bounded_messages():
    body = "a" * 2001
    channel = RecordingChannel()

    await send_split_message(channel, body, DEPS)

    assert len(channel.sent) == 2
    assert "".join(content for content, _ in channel.sent) == body
    assert all(len(content) <= 2000 for content, _ in channel.sent)


@pytest.mark.asyncio
async def test_every_chunk_including_the_prefix_stays_within_2000():
    body = "a" * 2000
    prefix = "<@42> "
    channel = RecordingChannel()

    await send_split_message(channel, body, DEPS, mention_prefix=prefix)

    assert len(channel.sent) == 2
    assert channel.sent[0][0].startswith(prefix)
    assert "".join(content for content, _ in channel.sent) == f"{prefix}{body}"
    assert all(len(content) <= 2000 for content, _ in channel.sent)


def test_embed_description_accepts_4096_and_truncates_4097():
    accepted, accepted_metadata = citation_embed_formatter.create_citation_embed("a" * 4096, {})
    assert accepted_metadata["was_truncated"] is False
    assert len(accepted.description) == 4096

    truncated, truncated_metadata = citation_embed_formatter.create_citation_embed("a" * 4097, {})
    assert truncated_metadata["was_truncated"] is True
    assert truncated.description.endswith("...")
    assert len(truncated.description) == 3843


@pytest.mark.asyncio
async def test_safe_embed_limit_holds_at_3840_and_splits_at_3841():
    exact = RecordingChannel()
    await send_split_message_with_embed(exact, "a" * 3840, DEPS, discord.Embed())
    assert len(exact.sent) == 1
    assert len(exact.sent[0][1]["embed"].description) == 3840

    over = RecordingChannel()
    await send_split_message_with_embed(over, "a" * 3841, DEPS, discord.Embed())
    assert len(over.sent) == 2
    assert len(over.sent[0][1]["embed"].description) == 3840
    assert over.sent[1][0] == "a"


@pytest.mark.parametrize("depth", [MAX_SPLIT_RECURSION, MAX_SPLIT_RECURSION + 1])
@pytest.mark.asyncio
async def test_embed_recursion_guard_sends_one_truncated_reply(depth):
    channel = RecordingChannel()

    await send_split_message_with_embed(
        channel,
        "a" * 5000,
        DEPS,
        discord.Embed(),
        _recursion_depth=depth,
    )

    assert len(channel.sent) == 1
    content, kwargs = channel.sent[0]
    assert len(content) <= 2000
    assert "truncated" in content
    assert "embed" not in kwargs


@pytest.mark.asyncio
async def test_health_monitor_loop_visits_healthy_and_raising_clients():
    healthy = SimpleNamespace(
        models=SimpleNamespace(
            list=AsyncMock(
                return_value=SimpleNamespace(data=[SimpleNamespace(id=DEFAULT_OPENAI_MODEL)])
            )
        )
    )
    raising = SimpleNamespace(
        models=SimpleNamespace(list=AsyncMock(side_effect=RuntimeError("provider down")))
    )
    monitor = APIHealthMonitor()

    results = await monitor.run_all_health_checks(
        {"openai": healthy, "perplexity": raising},
        {
            "GPT_MODEL": DEFAULT_OPENAI_MODEL,
            "PERPLEXITY_MODEL": DEFAULT_PERPLEXITY_MODEL,
        },
    )

    assert set(results) == {"openai", "perplexity"}
    assert results["openai"].status == "healthy"
    assert results["perplexity"].status == "unhealthy"
    aggregate = "unhealthy" if any(r.status != "healthy" for r in results.values()) else "healthy"
    assert aggregate == "unhealthy"
    assert monitor.metrics["openai"].successful_checks == 1
    assert monitor.metrics["perplexity"].failed_checks == 1


@pytest.mark.asyncio
async def test_fourth_failing_rate_limit_call_is_refused_by_cooldown(monkeypatch):
    now = 100.0
    monkeypatch.setattr("src.rate_limits.time.monotonic", lambda: now)
    limiter = RateLimiter()
    limiter.check_rate_limit = Mock(side_effect=ValueError("clock failure"))
    user = SimpleNamespace(id=7, name="user")

    assert await check_rate_limit(user, limiter, 10, 60, LOGGER) is True
    assert await check_rate_limit(user, limiter, 10, 60, LOGGER) is True
    assert await check_rate_limit(user, limiter, 10, 60, LOGGER) is False

    cooldown_until = limiter.fail_open_cooldown_until
    assert cooldown_until == now + 60
    assert await check_rate_limit(user, limiter, 10, 60, LOGGER) is False
    assert limiter.fail_open_cooldown_until == cooldown_until
    assert limiter.fail_open_errors == 1


@pytest.mark.asyncio
async def test_custom_emoji_does_not_move_openai_conversation_to_perplexity():
    conversation_key = "g:1:c:1"
    manager = ThreadSafeConversationManager()
    manager.add_message(
        conversation_key=conversation_key,
        role="assistant",
        content="an earlier OpenAI answer",
        metadata={"ai_service": "openai"},
    )
    assert manager.get_recent_ai_service(conversation_key=conversation_key) == "openai"

    openai_create = AsyncMock(return_value=_completion("OpenAI answer"))
    perplexity_create = AsyncMock(return_value=_completion("Perplexity answer"))
    clients = AIClients(
        openai=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=openai_create))
        ),
        perplexity=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=perplexity_create))
        ),
    )
    request = AIRequest(
        message="please <:today:123456789>",
        user=SimpleNamespace(id=1),
        conversation_manager=manager,
        logger=LOGGER,
        conversation_key=conversation_key,
    )

    response, _suppress, _embed = await _process_hybrid_mode(
        request,
        [],
        clients,
        AIConfig(),
    )

    assert response == "OpenAI answer"
    openai_create.assert_awaited_once()
    perplexity_create.assert_not_awaited()
