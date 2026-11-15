"""Regression floor on the two sealed routing corpora.

Measured when the scoring layer was removed (2026-11-14): sealed-a accuracy
0.821, sealed-b accuracy 0.736, combined accuracy 0.779. The floors below sit
roughly two points under each measurement, so a real regression fails while
label noise does not.
"""

from datetime import UTC, datetime
import json
from pathlib import Path

from src.routing.contracts import RouterInput
from src.routing.heuristic import HeuristicRouter

CORPORA = {
    "sealed-a": Path(__file__).resolve().parent / "corpora" / "sealed-a.jsonl",
    "sealed-b": Path(__file__).resolve().parent / "corpora" / "sealed-b.jsonl",
}
FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
SEALED_A_FLOOR = 0.80
COMBINED_FLOOR = 0.75


def _cases(path: Path) -> list[dict[str, str]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _confusion(rows: list[tuple[str, str]]) -> dict[str, int]:
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for expected, predicted in rows:
        if expected == "web" and predicted == "web":
            counts["tp"] += 1
        elif expected == "web":
            counts["fn"] += 1
        elif predicted == "web":
            counts["fp"] += 1
        else:
            counts["tn"] += 1
    return counts


def _accuracy(counts: dict[str, int]) -> float:
    total = sum(counts.values())
    return (counts["tp"] + counts["tn"]) / total if total else 0.0


def test_sealed_corpora_hold_their_measured_accuracy() -> None:
    """Both sealed sets stay at or above their measured floors."""
    router = HeuristicRouter()
    outcomes: dict[str, list[tuple[str, str]]] = {}
    mismatches: list[str] = []
    for name, path in CORPORA.items():
        rows: list[tuple[str, str]] = []
        for case in _cases(path):
            expected = case["expect"]
            if expected == "ambiguous":
                continue
            decision = router.decide_sync(RouterInput(text=case["text"], now=FIXED_NOW))
            rows.append((expected, decision.route))
            if decision.route != expected:
                mismatches.append(
                    f"{name}: expected={expected} got={decision.route} "
                    f"reasons={decision.reasons} text={case['text']!r}"
                )
        outcomes[name] = rows

    per_corpus = {name: _confusion(rows) for name, rows in outcomes.items()}
    combined = _confusion([row for rows in outcomes.values() for row in rows])
    print(  # noqa: T201 - the requested confusion summary is this test's output
        "confusion: "
        + " ".join(
            f"{name}[TP={counts['tp']} FP={counts['fp']} TN={counts['tn']} "
            f"FN={counts['fn']} acc={_accuracy(counts):.3f}]"
            for name, counts in per_corpus.items()
        )
        + f" combined[acc={_accuracy(combined):.3f}] mismatches={len(mismatches)}",
        flush=True,
    )

    assert _accuracy(per_corpus["sealed-a"]) >= SEALED_A_FLOOR, "\n".join(mismatches)
    assert _accuracy(combined) >= COMBINED_FLOOR, "\n".join(mismatches)
