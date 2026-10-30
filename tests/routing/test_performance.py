"""Every 2,000-character message stays within the routing latency budgets."""

from datetime import UTC, datetime
import math
import sys
from time import perf_counter

import pytest

from src.routing.contracts import RouterInput
from src.routing.heuristic import HeuristicRouter

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
ITERATIONS = 300
P50_BUDGET_MS = 5.0
P99_BUDGET_MS = 25.0
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


def _percentile(samples: list[float], quantile: float) -> float:
    index = max(0, math.ceil(len(samples) * quantile) - 1)
    return samples[index]


@pytest.mark.skipif(
    "coverage" in sys.modules,
    reason="coverage instrumentation distorts latency measurements",
)
@pytest.mark.parametrize(("label", "text"), INPUTS.items(), ids=tuple(INPUTS))
def test_p99_latency_for_every_input_shape(label: str, text: str) -> None:
    """Separate the router's own cost from noise on the machine running it.

    p50 measures the code: on a quiet machine the slowest shape takes about
    1.6 ms, so the 5 ms budget leaves room for a slower host without hiding a
    regression. p99 measures the code plus the machine: scheduler delays and
    co-tenant load pushed the same code from 2.5 ms to 11 ms on a busy host.
    Its 25 ms bound is a sanity ceiling, not a performance target, and exists
    to catch the return of a complexity regression rather than to benchmark.
    The input once took about 260 ms per decision, so 25 ms still catches that
    quadratic blowup by an order of magnitude.
    """
    router = HeuristicRouter()
    request = RouterInput(text=text, now=FIXED_NOW)
    for _ in range(5):
        router.decide_sync(request)

    samples: list[float] = []
    for _ in range(ITERATIONS):
        started = perf_counter()
        router.decide_sync(request)
        samples.append((perf_counter() - started) * 1000.0)

    samples.sort()
    p50 = _percentile(samples, 0.50)
    p99 = _percentile(samples, 0.99)
    sys.stdout.write(f"{label}: p50={p50:.4f} ms p99={p99:.4f} ms over {ITERATIONS} decisions\n")
    assert p50 < P50_BUDGET_MS, f"{label}: p50={p50:.4f} ms exceeds {P50_BUDGET_MS} ms"
    assert p99 < P99_BUDGET_MS, f"{label}: p99={p99:.4f} ms exceeds {P99_BUDGET_MS} ms"
