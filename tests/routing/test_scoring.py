"""Scoring invariants, the no-bearing gate, and the cache policy."""

from datetime import UTC, datetime
import json
from pathlib import Path

from src.routing.contracts import RouterConfig, RouterInput
from src.routing.features import Cue, extract_cues, extract_overrides, views
from src.routing.heuristic import HeuristicRouter
from src.routing.lexicon import Lexicon
from src.routing.scoring import decide, score

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
CORPUS_PATH = Path(__file__).resolve().parents[1] / "routing_corpus_v0.jsonl"
LEXICON = Lexicon.load()


def _cases() -> list[dict[str, str]]:
    return [
        json.loads(line)
        for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _cues(text: str) -> tuple[Cue, ...]:
    text_views = views(text)
    return (
        *extract_overrides(text_views, LEXICON),
        *extract_cues(text_views, LEXICON, clock=FIXED_NOW.date),
    )


def test_score_equals_the_sum_of_evidence_weights_for_every_corpus_case() -> None:
    """The trace is the decision: the score is exactly the applied weights."""
    router = HeuristicRouter()
    for case in _cases():
        decision = router.decide_sync(RouterInput(text=case["text"], now=FIXED_NOW))
        assert decision.score == sum(item.weight for item in decision.evidence)


def test_framing_alone_can_never_decide() -> None:
    """A huge positive framing weight still cannot override the bearing gate."""
    framing = Cue(
        signal="frame.opinion",
        klass="framing",
        span=None,
        detail="opinion",
        weight=10.0,
    )

    scored = score((framing,), RouterConfig())
    decision = decide((framing,), RouterConfig(), text="what do you think")

    assert scored.value > 0
    assert not scored.has_bearing
    assert decision.route == "local"
    assert decision.band == "confident"


def test_no_bearing_cue_forces_local_however_question_shaped_the_text() -> None:
    """The gate is a rule, not a threshold: capital-of-France stays local."""
    config = RouterConfig()
    decision = decide(
        _cues("what is the capital of France"),
        config,
        text="what is the capital of France",
    )

    assert decision.route == "local"
    assert decision.band == "confident"
    assert not any(item.klass == "bearing" for item in decision.evidence)


def test_cache_is_disabled_for_the_unsure_band() -> None:
    """A decision between the two thresholds is not safe to cache."""
    cue = Cue(
        signal="pred.status",
        klass="bearing",
        span=None,
        detail="down",
        weight=-0.3,
    )

    decision = decide((cue,), RouterConfig(), text="is it down")

    assert decision.band == "unsure"
    assert not decision.cache.cacheable


def test_cache_is_disabled_for_a_local_route_that_carried_bearing_cues() -> None:
    """A bearing cue that still lands on local is not a stable local answer."""
    cue = Cue(
        signal="pred.status",
        klass="bearing",
        span=None,
        detail="down",
        weight=-2.0,
    )

    decision = decide((cue,), RouterConfig(), text="down")

    assert decision.route == "local"
    assert decision.band == "confident"
    assert not decision.cache.cacheable


def test_cache_is_disabled_for_url_overrides() -> None:
    """A URL instruction is live input, so the answer is not cached."""
    text = "check https://example.com/status"
    cues = _cues(text)

    assert any(cue.signal == "override.url" for cue in cues)
    decision = decide(cues, RouterConfig(), text=text)
    assert decision.route == "web"
    assert not decision.cache.cacheable


def test_cache_is_enabled_for_a_confident_web_or_plain_local_decision() -> None:
    """The default is cacheable once neither exception applies."""
    web = decide(_cues("is github down"), RouterConfig(), text="is github down")
    local = decide(_cues("happy birthday"), RouterConfig(), text="happy birthday")

    assert web.route == "web"
    assert web.cache.cacheable
    assert local.route == "local"
    assert local.cache.cacheable


def test_cache_is_disabled_for_empty_and_mention_only_input() -> None:
    """No content means there is nothing worth caching."""
    for text in ("", "   ", "<@123>"):
        decision = decide((), RouterConfig(), text=text)

        assert decision.route == "local"
        assert decision.band == "confident"
        assert not decision.cache.cacheable
