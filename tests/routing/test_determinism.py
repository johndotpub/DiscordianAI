"""Identical inputs produce identical decisions."""

from dataclasses import replace
from datetime import UTC, datetime

from src.routing.contracts import RouterInput
from src.routing.heuristic import HeuristicRouter

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
CALLS = 100


def test_one_hundred_identical_calls_give_identical_decisions() -> None:
    """Only the measured latency may differ between repeated calls."""
    router = HeuristicRouter()
    request = RouterInput(
        text="is github down and what changed in kubernetes since 1.30",
        now=FIXED_NOW,
    )

    first = replace(router.decide_sync(request), latency_ms=0.0)
    for _ in range(CALLS - 1):
        decision = replace(router.decide_sync(request), latency_ms=0.0)
        assert decision == first
