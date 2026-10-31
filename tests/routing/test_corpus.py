"""Run the labelled routing corpus and print the confusion matrix."""

from datetime import UTC, datetime
import json
from pathlib import Path

from src.routing.contracts import RouterInput
from src.routing.heuristic import HeuristicRouter

CORPUS_PATH = Path(__file__).resolve().parents[1] / "routing_corpus_v0.jsonl"
FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)


def _cases() -> list[dict[str, str]]:
    return [
        json.loads(line)
        for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_corpus_reports_the_confusion_matrix() -> None:
    """Measure the heuristic on the corpus without imposing a floor yet."""
    router = HeuristicRouter()
    true_positive = false_positive = true_negative = false_negative = 0
    for case in _cases():
        decision = router.decide_sync(RouterInput(text=case["text"], now=FIXED_NOW))
        expected_web = case["route"] == "web"
        predicted_web = decision.route == "web"
        if expected_web and predicted_web:
            true_positive += 1
        elif expected_web and not predicted_web:
            false_negative += 1
        elif not expected_web and predicted_web:
            false_positive += 1
        else:
            true_negative += 1

    total = true_positive + false_positive + true_negative + false_negative
    precision = true_positive / (true_positive + false_positive) if true_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive else 0.0
    accuracy = (true_positive + true_negative) / total if total else 0.0
    print(  # noqa: T201 - the requested corpus report is this test's output
        f"TP={true_positive} FP={false_positive} TN={true_negative} FN={false_negative} "
        f"precision={precision:.3f} recall={recall:.3f} accuracy={accuracy:.3f} "
        f"total={total}",
        flush=True,
    )
