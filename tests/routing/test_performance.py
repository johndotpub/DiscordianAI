"""Every 2,000-character message stays under the routing latency budget."""

from datetime import UTC, datetime
import math
import sys
from time import perf_counter

import pytest

from src.routing.contracts import RouterInput
from src.routing.heuristic import HeuristicRouter

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
ITERATIONS = 200
P99_BUDGET_MS = 3.0
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


@pytest.mark.skipif(
    "coverage" in sys.modules,
    reason="coverage instrumentation distorts latency measurements",
)
@pytest.mark.parametrize(("label", "text"), INPUTS.items(), ids=tuple(INPUTS))
def test_p99_latency_for_every_input_shape(label: str, text: str) -> None:
    """Measure the 99th percentile on adversarial and realistic text."""
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
    index = max(0, math.ceil(len(samples) * 0.99) - 1)
    p99 = samples[index]
    sys.stdout.write(f"{label}: p99={p99:.4f} ms over {ITERATIONS} decisions\n")
    assert p99 < P99_BUDGET_MS
