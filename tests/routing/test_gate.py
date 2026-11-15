"""The six-step gate: overrides, bearing, inheritance, and the local default."""

from datetime import UTC, datetime

import pytest

from src.routing.contracts import ConversationContext, RouterInput, Turn
from src.routing.features import Cue
from src.routing.gate import decide
from src.routing.heuristic import HeuristicRouter

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
ROUTER = HeuristicRouter()


def _decide(text: str, context: ConversationContext | None = None):
    return ROUTER.decide_sync(
        RouterInput(text=text, context=context or ConversationContext(), now=FIXED_NOW)
    )


def _context(route: str) -> ConversationContext:
    return ConversationContext(
        turns=(
            Turn(role="user", text="what is a monad"),
            Turn(role="assistant", text="a monad is a design pattern", route=route),
        ),
        last_route=route,
    )


TABLE = [
    (
        "override beats bearing",
        "search the web for is github down",
        ("override:web_instruction", "bearing:pred.status"),
        "web",
    ),
    (
        "web override beats local instruction",
        "answer from memory but search the web for python",
        ("override:web_instruction",),
        "web",
    ),
    (
        "url override",
        "check https://example.com/status",
        ("override:url",),
        "web",
    ),
    (
        "supplied artifact beats bearing",
        "summarize: the api is down",
        ("local:supplied_artifact",),
        "local",
    ),
    (
        "bearing cue",
        "is github down",
        ("bearing:pred.status",),
        "web",
    ),
    (
        "no signal",
        "hello there",
        ("local:default",),
        "local",
    ),
    (
        "empty message",
        "",
        ("local:default",),
        "local",
    ),
]


@pytest.mark.parametrize(("label", "text", "reasons", "route"), TABLE)
def test_gate_table(label: str, text: str, reasons: tuple[str, ...], route: str) -> None:
    """Each gate step chooses its route and stable reason codes."""
    decision = _decide(text)

    assert decision.route == route, label
    assert decision.reasons == reasons, label


def test_code_fenced_url_is_not_a_url_override() -> None:
    """Overrides are extracted from masked text, so a fenced URL stays local."""
    decision = _decide("```\nhttps://example.com/status\n```")

    assert decision.route == "local"
    assert "override:url" not in decision.reasons


def test_follow_up_inherits_the_prior_web_route() -> None:
    """A short follow-up with a recent assistant turn inherits web."""
    decision = _decide("tell me more", _context("web"))

    assert decision.route == "web"
    assert decision.reasons == ("inherited:web",)


def test_follow_up_inherits_the_prior_local_route() -> None:
    """A short follow-up with a recent assistant turn inherits local."""
    decision = _decide("tell me more", _context("local"))

    assert decision.route == "local"
    assert decision.reasons == ("inherited:local",)


def test_reasons_are_capped_and_sorted_by_span_then_signal() -> None:
    """Unstable ordering or an unbounded trace must not reach telemetry."""
    cues = [
        Cue(signal=f"pred.signal{index}", klass="bearing", span=(index, index + 1), detail="x")
        for index in range(10)
    ]

    decision = decide(reversed(cues), text="many cues")

    assert decision.reasons == tuple(f"bearing:pred.signal{index}" for index in range(8))


def test_decision_is_frozen() -> None:
    """A decision cannot be rewritten after the orchestrator records it."""
    decision = _decide("is github down")

    with pytest.raises(AttributeError):
        decision.route = "local"  # type: ignore[misc]
