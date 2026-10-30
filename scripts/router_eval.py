#!/usr/bin/env python3
"""Score the routing heuristic on a JSONL corpus, overall and per slice."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from importlib import import_module
import json
import math
from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.routing.contracts import RouterInput  # noqa: E402 - repo root is added above
from src.routing.heuristic import HeuristicRouter  # noqa: E402 - repo root is added above

_EXPECTED = frozenset({"web", "local", "ambiguous"})
_Z_95 = 1.959963984540054
_DEFAULT_SLICE_FIELD = "slice"
_METRIC_NAMES = ("recall", "precision", "accuracy")


@dataclass(frozen=True, slots=True)
class Metrics:
    """Confusion counts and the rates derived from them."""

    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def n(self) -> int:
        """Return the number of scored rows."""
        return self.tp + self.fp + self.tn + self.fn

    @property
    def precision(self) -> float:
        """Return TP / (TP + FP), or zero when there are no web predictions."""
        denominator = self.tp + self.fp
        return self.tp / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        """Return TP / (TP + FN), or zero when there are no web rows."""
        denominator = self.tp + self.fn
        return self.tp / denominator if denominator else 0.0

    @property
    def accuracy(self) -> float:
        """Return (TP + TN) / n, or zero for an empty set."""
        return (self.tp + self.tn) / self.n if self.n else 0.0

    @property
    def recall_ci95(self) -> tuple[float, float]:
        """Return the 95% Wilson score interval around recall."""
        return _wilson_interval(self.tp, self.tp + self.fn)

    def add(self, expected_web: bool, predicted_web: bool) -> Metrics:
        """Return the counts with one observation folded in."""
        if expected_web and predicted_web:
            return Metrics(self.tp + 1, self.fp, self.tn, self.fn)
        if expected_web:
            return Metrics(self.tp, self.fp, self.tn, self.fn + 1)
        if predicted_web:
            return Metrics(self.tp, self.fp + 1, self.tn, self.fn)
        return Metrics(self.tp, self.fp, self.tn + 1, self.fn)

    def as_dict(self) -> dict[str, Any]:
        """Return machine-readable metrics with recall and its interval first."""
        low, high = self.recall_ci95
        return {
            "recall": self.recall,
            "recall_ci95": [low, high],
            "recall_ci_low": low,
            "recall_ci_high": high,
            "precision": self.precision,
            "accuracy": self.accuracy,
            "n": self.n,
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
        }


def _wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    if trials <= 0:
        return (0.0, 1.0)
    proportion = successes / trials
    z_squared = _Z_95 * _Z_95
    denominator = 1.0 + z_squared / trials
    centre = proportion + z_squared / (2.0 * trials)
    margin = _Z_95 * math.sqrt(
        proportion * (1.0 - proportion) / trials + z_squared / (4.0 * trials * trials)
    )
    low = max(0.0, (centre - margin) / denominator)
    high = min(1.0, (centre + margin) / denominator)
    return (low, high)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"{path}:{line_number}: invalid JSON: {exc}"
            raise SystemExit(msg) from exc
        if not isinstance(row, dict):
            msg = f"{path}:{line_number}: row must be an object"
            raise SystemExit(msg)
        if not isinstance(row.get("text"), str):
            msg = f"{path}:{line_number}: 'text' must be a string"
            raise SystemExit(msg)
        if row.get("expect") not in _EXPECTED:
            msg = f"{path}:{line_number}: 'expect' must be web, local, or ambiguous"
            raise SystemExit(msg)
        rows.append(row)
    return rows


def _slice_value(row: Mapping[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _score_rows(
    rows: Iterable[Mapping[str, Any]],
    predict: Callable[[str], bool],
    slice_field: str,
) -> tuple[Metrics, dict[str, Metrics], int]:
    overall = Metrics()
    slices: dict[str, Metrics] = {}
    excluded = 0
    for row in rows:
        expected = row["expect"]
        if expected == "ambiguous":
            excluded += 1
            continue
        predicted_web = predict(str(row["text"]))
        expected_web = expected == "web"
        overall = overall.add(expected_web, predicted_web)
        name = _slice_value(row, slice_field)
        if name is not None:
            slices[name] = slices.get(name, Metrics()).add(expected_web, predicted_web)
    return overall, dict(sorted(slices.items())), excluded


def evaluate(
    rows: Sequence[Mapping[str, Any]],
    predict: Callable[[str], bool],
    *,
    slice_field: str = _DEFAULT_SLICE_FIELD,
) -> dict[str, Any]:
    """Return overall and per-slice metrics for ``rows``."""
    overall, slices, excluded = _score_rows(rows, predict, slice_field)
    return {
        "n_total": len(rows),
        "n_scored": overall.n,
        "n_excluded": excluded,
        "excluded": excluded,
        "overall": overall.as_dict(),
        "slices": {name: metrics.as_dict() for name, metrics in slices.items()},
    }


def _predict_heuristic(text: str) -> bool:
    decision = HeuristicRouter().decide_sync(RouterInput(text=text))
    return decision.route == "web"


def _predict_incumbent(text: str) -> bool:
    module = import_module("src.smart_orchestrator")
    return bool(module.should_use_web_search(text))


def _delta(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, float]:
    return {name: float(current[name]) - float(baseline[name]) for name in _METRIC_NAMES}


def _format_metrics(label: str, metrics: Mapping[str, Any]) -> str:
    low, high = metrics["recall_ci95"]
    return (
        f"{label}: recall={metrics['recall']:.3f} "
        f"(95% CI {low:.3f}-{high:.3f}) "
        f"precision={metrics['precision']:.3f} "
        f"accuracy={metrics['accuracy']:.3f} "
        f"n={metrics['n']} TP={metrics['tp']} FP={metrics['fp']} "
        f"TN={metrics['tn']} FN={metrics['fn']}"
    )


def _emit(line: str) -> None:
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def _print_report(result: Mapping[str, Any], baseline: str) -> None:
    _emit(f"excluded={result['n_excluded']} ambiguous rows")
    _emit(_format_metrics("overall", result["overall"]))
    for name, metrics in result["slices"].items():
        _emit(_format_metrics(f"slice {name}", metrics))
    if baseline == "old" and "baseline" in result:
        _emit(_format_metrics("baseline old overall", result["baseline"]["overall"]))
        for name, metrics in result["baseline"]["slices"].items():
            _emit(_format_metrics(f"baseline old slice {name}", metrics))
        delta = result["delta"]["overall"]
        _emit(
            "delta overall: "
            f"recall={delta['recall']:+.3f} "
            f"precision={delta['precision']:+.3f} "
            f"accuracy={delta['accuracy']:+.3f}"
        )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path, help="JSONL corpus to score")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit JSON")
    parser.add_argument(
        "--baseline",
        choices=("old", "none"),
        default="none",
        help="also score the incumbent regex router",
    )
    parser.add_argument(
        "--slice",
        default=_DEFAULT_SLICE_FIELD,
        metavar="FIELD",
        help="row field used to group per-slice metrics (default: slice)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the evaluator and return a process exit code."""
    args = _parse_args(argv)
    if not args.corpus.is_file():
        msg = f"corpus not found: {args.corpus}"
        raise SystemExit(msg)
    rows = _read_rows(args.corpus)
    result = evaluate(rows, _predict_heuristic, slice_field=args.slice)
    result["corpus"] = str(args.corpus)
    if args.baseline == "old":
        baseline = evaluate(rows, _predict_incumbent, slice_field=args.slice)
        result["baseline"] = baseline
        result["delta"] = {
            "overall": _delta(result["overall"], baseline["overall"]),
            "slices": {
                name: _delta(metrics, baseline["slices"].get(name, Metrics().as_dict()))
                for name, metrics in result["slices"].items()
            },
        }
    if args.as_json:
        _emit(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        _print_report(result, args.baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
