"""The standalone evaluator reports JSON and excludes ambiguous rows."""

import json
from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "router_eval.py"
ROWS = [
    {"text": "is github down", "expect": "web", "slice": "status"},
    {"text": "what does idempotent mean?", "expect": "local", "slice": "technical"},
    {"text": "is discord down", "expect": "ambiguous", "slice": "status"},
    {"text": "what is a monad?", "expect": "web", "slice": "technical"},
]


def _fixture(tmp_path: Path) -> Path:
    path = tmp_path / "corpus.jsonl"
    path.write_text(
        "\n".join(json.dumps(row) for row in ROWS) + "\n",
        encoding="utf-8",
    )
    return path


def _run(path: Path, *extra: str) -> dict:
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and script path
        [sys.executable, str(SCRIPT), "--corpus", str(path), "--json", *extra],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_json_shape_and_ambiguous_rows_are_excluded(tmp_path: Path) -> None:
    """Ambiguous rows never enter the confusion matrix."""
    result = _run(_fixture(tmp_path))

    assert result["n_total"] == 4
    assert result["n_scored"] == 3
    assert result["n_excluded"] == result["excluded"] == 1
    assert result["overall"]["n"] == 3
    assert result["overall"]["tp"] == 1
    assert result["overall"]["fn"] == 1
    assert result["overall"]["tn"] == 1
    assert result["overall"]["fp"] == 0
    assert result["overall"]["recall"] == 0.5
    assert result["overall"]["precision"] == 1.0
    low, high = result["overall"]["recall_ci95"]
    assert 0.0 <= low < result["overall"]["recall"] < high <= 1.0
    assert result["overall"]["recall_ci_low"] == low
    assert result["overall"]["recall_ci_high"] == high


def test_slices_are_grouped_from_the_requested_field(tmp_path: Path) -> None:
    """--slice chooses the row field; missing fields do not create a group."""
    path = _fixture(tmp_path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["kind"] = row.pop("slice")
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = _run(path, "--slice", "kind")

    assert set(result["slices"]) == {"status", "technical"}
    assert result["slices"]["status"]["n"] == 1
    assert result["slices"]["status"]["tp"] == 1
    assert result["slices"]["technical"]["n"] == 2
    assert result["slices"]["technical"]["tn"] == 1
    assert result["slices"]["technical"]["fn"] == 1
