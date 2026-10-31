#!/usr/bin/env python3
"""Check or regenerate the golden-behaviour fixtures.

Without arguments the script reports drift and exits 1 when current behaviour
no longer matches the recorded fixtures.  ``--write`` rewrites the fixtures and
requires ``GOLDEN_REGEN=1`` in the environment.
"""

# ruff: noqa: T201

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.golden_cases import CASES_BY_SURFACE, SURFACES  # noqa: E402
from tests.golden_runner import (  # noqa: E402
    fixture_path,
    load_fixture,
    run_all_sync,
)


def _short(value: Any, limit: int = 240) -> str:
    text = repr(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _first_difference(  # noqa: PLR0911
    expected: Any, actual: Any, path: str = ""
) -> tuple[str, Any, Any]:
    if type(expected) is not type(actual):
        return path or "<root>", expected, actual
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in expected:
                return child_path, "<missing>", actual[key]
            if key not in actual:
                return child_path, expected[key], "<missing>"
            if expected[key] != actual[key]:
                return _first_difference(expected[key], actual[key], child_path)
        return path or "<root>", expected, actual
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}.length", len(expected), len(actual)
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual, strict=True)):
            child_path = f"{path}[{index}]"
            if expected_item != actual_item:
                return _first_difference(expected_item, actual_item, child_path)
        return path or "<root>", expected, actual
    return path or "<root>", expected, actual


def _write_fixtures(actual: dict[str, dict[str, Any]]) -> None:
    for surface in SURFACES:
        path = fixture_path(surface)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"surface": surface, "cases": actual[surface]}
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path.relative_to(REPO_ROOT)} ({len(actual[surface])} cases)")


def _check_fixtures(actual: dict[str, dict[str, Any]]) -> int:
    drift_count = 0
    for surface in SURFACES:
        case_ids = [case["id"] for case in CASES_BY_SURFACE[surface]]
        path = fixture_path(surface)
        if not path.exists():
            print(f"{surface}: MISSING fixture {path.relative_to(REPO_ROOT)}")
            drift_count += len(case_ids)
            continue

        fixture = load_fixture(surface)
        if fixture.get("surface") != surface:
            print(f"{surface}: surface field is {fixture.get('surface')!r}")
            drift_count += 1
        expected_cases = fixture.get("cases", {})

        for case_id in case_ids:
            if case_id not in expected_cases:
                print(f"{surface}/{case_id}: missing recorded expectation")
                drift_count += 1
                continue
            if actual[surface][case_id] != expected_cases[case_id]:
                drift_count += 1
                field, expected_value, actual_value = _first_difference(
                    expected_cases[case_id], actual[surface][case_id]
                )
                print(f"{surface}/{case_id}: drift at {field}")
                print(f"  expected: {_short(expected_value)}")
                print(f"  actual:   {_short(actual_value)}")

        for extra_id in sorted(set(expected_cases) - set(case_ids)):
            print(f"{surface}/{extra_id}: fixture entry no longer has a case")
            drift_count += 1

    if drift_count:
        print(f"Drift detected: {drift_count} difference(s).")
        return 1

    print("Golden fixtures match current behaviour.")
    return 0


def main() -> int:
    """Run the drift check or rewrite fixtures when explicitly requested."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite fixtures (requires GOLDEN_REGEN=1)",
    )
    args = parser.parse_args()

    if args.write and os.environ.get("GOLDEN_REGEN") != "1":
        print("Refusing to rewrite golden fixtures: set GOLDEN_REGEN=1 to confirm.")
        return 1

    actual = run_all_sync()
    if args.write:
        _write_fixtures(actual)
        return 0
    return _check_fixtures(actual)


if __name__ == "__main__":
    raise SystemExit(main())
