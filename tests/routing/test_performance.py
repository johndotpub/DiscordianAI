"""A 2,000-character message stays well under the routing latency budget."""

from datetime import UTC, datetime
import math
import sys
from time import perf_counter

import pytest

from src.routing.contracts import RouterInput
from src.routing.heuristic import HeuristicRouter

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
ITERATIONS = 500
MESSAGE = (
    "is github down and what changed in kubernetes since 1.30 "
    "did python 3.13 ship and what is the weather in london "
)
LONG_MESSAGE = (MESSAGE * (2_000 // len(MESSAGE) + 1))[:2_000]
P99_BUDGET_MS = 3.0


@pytest.mark.skipif(
    "coverage" in sys.modules,
    reason="coverage instrumentation distorts latency measurements",
)
def test_p99_latency_for_a_two_thousand_character_message() -> None:
    """Measure the 99th percentile over at least 500 decisions."""
    router = HeuristicRouter()
    request = RouterInput(text=LONG_MESSAGE, now=FIXED_NOW)
    for _ in range(5):
        router.decide_sync(request)

    samples: list[float] = []
    for _ in range(ITERATIONS):
        started = perf_counter()
        router.decide_sync(request)
        samples.append((perf_counter() - started) * 1000.0)

    samples.sort()
    index = max(0, math.ceil(len(samples) * 0.99) - 1)
    p99 = samples[index]
    sys.stdout.write(f"p99={p99:.4f} ms over {ITERATIONS} decisions\n")
    assert p99 < P99_BUDGET_MS
