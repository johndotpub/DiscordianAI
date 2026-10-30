"""Regression cases for the narrow round 3b recall additions."""

import pytest

from src.routing.contracts import RouterInput
from src.routing.heuristic import HeuristicRouter
from src.routing.lexicon import Lexicon

LEXICON = Lexicon.load()
ROUTER = HeuristicRouter()


def _decide(text: str):
    return ROUTER.decide_sync(RouterInput(text=text))


@pytest.mark.parametrize(
    "text",
    [
        "is the minecraft server up rn?",
        "is the plugin alliance auth server down",
        "the arena server wiped",
        "is the server down",
    ],
)
def test_state_bare_adjacency_routes_service_nouns_to_web(text: str) -> None:
    """A service noun beside a state adjective is live status."""
    decision = _decide(text)

    assert decision.route == "web"
    assert any(item.signal in {"pred.status", "pred.release"} for item in decision.evidence)


def test_state_bare_adjacency_does_not_fire_without_a_service_noun() -> None:
    """A bare state adjective with no service subject is not enough."""
    decision = _decide("feeling down today")

    assert decision.route == "local"
    assert not any(item.signal == "pred.status" for item in decision.evidence)


def test_possessive_service_noun_is_not_a_bare_service_noun() -> None:
    """site's is a possessive surface form, not the bare noun site."""
    decision = _decide("site's down for me but works on mobile data, weird")

    assert decision.route == "local"


@pytest.mark.parametrize(
    "text",
    [
        "503s from the api",
        "the api is returning 502s",
        "cloudflare returns a 5xx on the endpoint",
    ],
)
def test_error_codes_near_a_service_noun_are_bearing(text: str) -> None:
    """An HTTP status token beside a service noun means an upstream fault."""
    decision = _decide(text)

    assert decision.route == "web"
    assert any(item.signal == "pred.error_code" for item in decision.evidence)


@pytest.mark.parametrize(
    "text",
    [
        "i got a 503 last week",
        "what does a 404 mean",
        "i once saw a 429 error",
    ],
)
def test_error_codes_without_a_nearby_service_noun_stay_local(text: str) -> None:
    """A bare status token or an unrelated service noun alone is not bearing."""
    decision = _decide(text)

    assert decision.route == "local"
    assert not any(item.signal == "pred.error_code" for item in decision.evidence)


@pytest.mark.parametrize(
    "text",
    [
        "is the new season live yet or does it unlock at midnight",
        "is it out of early access now",
        "the arena server wiped",
        "did the counter reset after the outage",
    ],
)
def test_new_release_state_terms_are_bearing(text: str) -> None:
    """The new release-state terms route as live release status."""
    decision = _decide(text)

    assert decision.route == "web"
    assert any(item.signal == "pred.release" for item in decision.evidence)


@pytest.mark.parametrize(
    "text",
    [
        "status page says operational",
        "give me today's headlines in one line each",
        "did they catch whoever was breaking into cars",
        "is there downtime scheduled",
        "the steam maintenance window is today",
        "did the wipe happen already",
    ],
)
def test_new_volatile_terms_are_bearing(text: str) -> None:
    """The new volatile-topic terms route as current information."""
    decision = _decide(text)

    assert decision.route == "web"
    assert any(item.signal == "topic.volatile" for item in decision.evidence)


@pytest.mark.parametrize(
    "text",
    [
        "did the city council vote on the bike lanes yet",
        "did the vote in parliament pass",
        "the proposal was rejected",
        "the studio got bought out",
        "did that bank get acquired",
        "the court ruled on the case",
    ],
)
def test_new_outcome_terms_are_bearing(text: str) -> None:
    """The new outcome terms route as decided events."""
    decision = _decide(text)

    assert decision.route == "web"
    assert any(item.signal == "pred.outcome" for item in decision.evidence)


def test_down_to_a_verb_is_willingness_not_status() -> None:
    """down to raid is an invitation, not a service outage."""
    decision = _decide("are you down to raid")

    assert decision.route == "local"
    assert not any(item.signal == "pred.status" for item in decision.evidence)


def test_willingness_guard_yields_to_another_bearing_cue() -> None:
    """A second bearing cue keeps the state adjective in play."""
    decision = _decide("the server is down to play and the price is up")

    assert decision.route == "web"
    assert any(item.signal == "pred.status" for item in decision.evidence)


@pytest.mark.parametrize(
    "text",
    [
        "is discord nitro worth it",
        "is serum worth it over vital",
    ],
)
def test_worth_it_is_opinion_and_stays_local(text: str) -> None:
    """worth it is an opinion frame, not a live price lookup."""
    decision = _decide(text)

    assert decision.route == "local"
    assert not any(item.signal == "topic.commerce" for item in decision.evidence)


def test_worth_followed_by_a_number_keeps_commerce_bearing() -> None:
    """A numeric worth remains a price question."""
    decision = _decide("worth 400")

    assert decision.route == "web"
    assert any(
        item.signal == "topic.commerce" and item.detail == "worth" for item in decision.evidence
    )


def test_worth_it_guard_yields_to_another_bearing_cue() -> None:
    """A simultaneous price cue keeps worth as commerce."""
    decision = _decide("the price is high but is it worth it")

    assert decision.route == "web"
    assert any(
        item.signal == "topic.commerce" and item.detail == "worth" for item in decision.evidence
    )


def test_fuzzy_neighbours_of_new_terms_stay_local() -> None:
    """Common words one edit from a new term do not become bearing."""
    for text in ("take a note", "the rules are simple", "the rest of the config", "my wife"):
        decision = _decide(text)
        assert decision.route == "local", text
