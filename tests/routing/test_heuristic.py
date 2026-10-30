"""The required routing behaviours, one test per group."""

from datetime import UTC, datetime

import pytest

from src.routing.contracts import ConversationContext, RouterInput, Turn
from src.routing.heuristic import HeuristicRouter

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
ROUTER = HeuristicRouter()


def _decide(text: str, context: ConversationContext | None = None):
    return ROUTER.decide_sync(
        RouterInput(
            text=text,
            context=context or ConversationContext(),
            now=FIXED_NOW,
        )
    )


def _context(route: str) -> ConversationContext:
    return ConversationContext(
        turns=(
            Turn(role="user", text="what is a monad"),
            Turn(role="assistant", text="a monad is a design pattern", route=route),
        ),
        last_route=route,
    )


@pytest.mark.parametrize(
    "text",
    [
        "is github down",
        "is discord having an outage",
        "is npm down",
        "whts the wether in london",
        "is githbu down",
    ],
)
def test_group_1_status_and_typos_route_to_web(text: str) -> None:
    """Status predicates, volatile topics, and one-edit typos need the web."""
    assert _decide(text).route == "web"


@pytest.mark.parametrize(
    "text",
    [
        "did python 3.13 ship",
        "what changed in kubernetes since 1.30",
        "any advisories for log4j",
        "what's the exchange rate for euros",
        "when does the iphone restock",
    ],
)
def test_group_2_versions_changes_and_advisories_route_to_web(text: str) -> None:
    """Version, change, advisory, rate, and restock signals need the web."""
    assert _decide(text).route == "web"


@pytest.mark.parametrize(
    "text",
    [
        "what's the going rate for a used road bike in san francisco",
        "how busy is the dmv right now",
        "is the bay bridge closed this morning",
    ],
)
def test_group_3_local_life_questions_route_to_web(text: str) -> None:
    """Price, busyness, and closure questions refer to live local state."""
    assert _decide(text).route == "web"


def test_group_4_contractions_do_not_change_the_route() -> None:
    """What is X and what's X produce the same local route."""
    plain = _decide("what is the capital of France")
    contracted = _decide("what's the capital of France")

    assert plain.route == contracted.route == "local"


@pytest.mark.parametrize(
    "text",
    [
        "thank you",
        "best regards",
        "happy birthday",
        "thanks sarah that fixed it",
    ],
)
def test_group_5_social_register_routes_local(text: str) -> None:
    """Social messages are framing-only and never trigger a search."""
    assert _decide(text).route == "local"


@pytest.mark.parametrize(
    "text",
    [
        "why does asyncio.gather swallow the first exception",
        "main.py",
        "package.json",
        "refactor this function",
        "find the bug in this loop",
    ],
)
def test_group_6_code_and_deictic_tasks_route_local(text: str) -> None:
    """Code shapes and references to the local task beat lookup framing."""
    assert _decide(text).route == "local"


@pytest.mark.parametrize(
    "text",
    [
        "i spoke to john smith yesterday about the migration",
        "work was brutal today",
        "i couldn't sleep last night",
    ],
)
def test_group_7_narrative_past_tense_routes_local(text: str) -> None:
    """A past-tense narrative is not a live-data question."""
    assert _decide(text).route == "local"


def test_group_8_follow_ups_inherit_only_when_a_prior_turn_exists() -> None:
    """Tomorrow with no history is live; tell-me-more follows the previous route."""
    assert _decide("what about tomorrow instead").route == "web"
    assert _decide("tell me more", _context("local")).route == "local"
    assert _decide("tell me more", _context("web")).route == "web"


def test_group_9_explicit_search_instructions_win() -> None:
    """An explicit search goes to web; an explicit memory request goes local."""
    assert _decide("search the web for the rust 2024 edition guide").route == "web"
    assert _decide("do not search, answer from memory").route == "local"


@pytest.mark.parametrize("text", ["", "   ", "🙂", "<@123>"])
def test_group_10_empty_and_non_word_input_is_confident_and_uncached(text: str) -> None:
    """No content is a confident local decision that must not be cached."""
    decision = _decide(text)

    assert decision.route == "local"
    assert decision.band == "confident"
    assert not decision.cache.cacheable
