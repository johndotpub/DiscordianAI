"""Every routing input shape does bounded cue work per decision."""

from datetime import UTC, datetime
from itertools import pairwise

import pytest

from src.routing import features
from src.routing.contracts import RouterInput
from src.routing.heuristic import HeuristicRouter

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
SIZES = (500, 1_000, 2_000)
MAX_GROWTH = 2.1
# The heaviest 2,000-character shape measured 1,001 clause evaluations
# ("dots"); 2,000 leaves clear headroom without allowing an unbounded scan.
CLAUSE_CEILING = 2_000
PATHOLOGICAL_INPUTS = {
    "dots": "a." * 1000,
    "letters": "a" * 2000,
    "punctuation": "!" * 2000,
    "fences": "```" * 600,
    "words": "word " * 400,
    "brackets": "(" * 2000,
}
REALISTIC_LOG_LINE = (
    "2026-10-30 12:00:01 INFO worker pid=4812 connected to postgres "
    "2026-10-30 12:00:02 DEBUG loaded src/main.py in 12ms "
    "2026-10-30 12:00:03 WARN retrying request id=9f2c attempt=1 "
    "2026-10-30 12:00:04 ERROR upstream timeout after 30s "
    "2026-10-30 12:00:05 INFO request completed status=200 "
)
REALISTIC_LOG = (REALISTIC_LOG_LINE * (2_000 // len(REALISTIC_LOG_LINE) + 1))[:2_000]
INPUTS = {**PATHOLOGICAL_INPUTS, "realistic-log": REALISTIC_LOG}


def _clause_counts(router: HeuristicRouter, text: str) -> list[int]:
    """Return the cue work for 500, 1,000, and 2,000 characters of ``text``."""
    counts: list[int] = []
    for size in SIZES:
        features._reset_decision_stats()
        router.decide_sync(RouterInput(text=text[:size], now=FIXED_NOW))
        counts.append(features._decision_stats()["clauses"])
    return counts


@pytest.mark.parametrize(("label", "text"), INPUTS.items(), ids=tuple(INPUTS))
def test_clause_count_grows_no_faster_than_the_input(label: str, text: str) -> None:
    """The clause counter, not a wall clock, proves the bound.

    A shared two-core CI machine makes millisecond budgets flaky even when the
    code is linear, so this test counts the clause and pattern matches the cue
    extractor processes. Each doubling of the input may add at most 2.1 times
    the previous work, and the 2,000-character case stays under an absolute
    ceiling. Revert check: rescanning the full text once per token makes the
    count grow with the square of the input and fails this assertion.
    """
    counts = _clause_counts(HeuristicRouter(), text)

    for previous, current in pairwise(counts):
        assert current <= MAX_GROWTH * previous + 1, f"{label}: clause counts {counts}"
    assert counts[-1] <= CLAUSE_CEILING, f"{label}: clause counts {counts}"


@pytest.mark.parametrize(("label", "text"), INPUTS.items(), ids=tuple(INPUTS))
def test_repeated_decisions_are_stable(label: str, text: str) -> None:
    """The same input decides identically twice, with no clock-dependent cue."""
    router = HeuristicRouter()
    request = RouterInput(text=text, now=FIXED_NOW)

    first = router.decide_sync(request)
    second = router.decide_sync(request)

    assert second.route == first.route, label
    assert second.reasons == first.reasons, label
