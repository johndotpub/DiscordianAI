"""Tests for the startup dependency gate.

The gate must reflect what ``src`` actually imports at runtime. The expected
set below is written by hand from the source tree, so a wrong algorithm inside
the gate cannot validate itself.
"""

import importlib.util
import logging
from pathlib import Path
import re
import tomllib

import pytest

from src import dependency_check as gate

# Third-party modules src imports unconditionally at runtime. Update this list
# when a new runtime import is added. Optional imports guarded by try/except,
# such as httpx2, are intentionally absent.
EXPECTED_RUNTIME_IMPORTS = {
    "aiohttp",
    "cachetools",
    "discord",
    "httpx",
    "openai",
    "structlog",
    "tree_sitter",
    "tree_sitter_markdown",
}

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
_DISTRIBUTION_NAME = re.compile(r"[A-Za-z0-9_.-]+")


def _declared_distributions() -> set[str]:
    """Return the lowercased distribution names declared as runtime dependencies."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    names = set()
    for requirement in project["dependencies"]:
        match = _DISTRIBUTION_NAME.match(requirement)
        assert match is not None, f"unreadable dependency requirement: {requirement}"
        names.add(match.group(0).casefold())
    return names


def _find_spec_without(*missing: str):
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name in missing:
            return None
        return real_find_spec(name, *args, **kwargs)

    return fake_find_spec


def test_checked_set_matches_the_hand_written_runtime_imports() -> None:
    """Every third-party runtime import is checked, and nothing else."""
    assert gate.get_required_imports() == EXPECTED_RUNTIME_IMPORTS


def test_every_declared_runtime_dependency_maps_to_an_expected_import() -> None:
    """The declared runtime packages and the expected import names agree."""
    declared = _declared_distributions()
    expected_distributions = {
        gate._DISTRIBUTION_ALIASES.get(name, name) for name in EXPECTED_RUNTIME_IMPORTS
    }

    # h2 is declared for httpx's HTTP/2 extra but src never imports it directly.
    assert "h2" in declared
    assert declared - {"h2"} == expected_distributions


def test_missing_httpx_reports_friendly_message(monkeypatch, caplog) -> None:
    """A missing httpx is reported by name with an install command, then exits."""
    monkeypatch.setattr(importlib.util, "find_spec", _find_spec_without("httpx"))

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc_info:
        gate.main()

    assert exc_info.value.code == 1
    assert "httpx" in caplog.text
    assert "pip install httpx" in caplog.text


def test_websockets_is_not_required_and_absence_is_harmless(monkeypatch) -> None:
    """websockets is only a transitive dependency, so the gate must not require it."""
    required = gate.get_required_imports()
    assert "websockets" not in required
    assert "websockets" not in gate.required_distributions()

    monkeypatch.setattr(importlib.util, "find_spec", _find_spec_without("websockets"))
    success, missing = gate.check_dependencies()

    assert success is True
    assert missing == []


def test_new_parser_dependencies_use_their_distribution_names() -> None:
    """Import names with underscores map to the installable distribution names."""
    distributions = gate.required_distributions()

    assert distributions["tree_sitter"] == "tree-sitter"
    assert distributions["tree_sitter_markdown"] == "tree-sitter-markdown"


def test_satisfied_environment_passes() -> None:
    """The test environment has every required dependency installed."""
    success, missing = gate.check_dependencies()
    assert success is True
    assert missing == []


def test_entry_point_reports_a_missing_package_before_importing_it(monkeypatch, capsys):
    """The friendly gate runs before the entry module imports structlog."""
    from src import main as entry_point

    monkeypatch.setattr(importlib.util, "find_spec", _find_spec_without("structlog"))

    with pytest.raises(SystemExit) as exc_info:
        entry_point.main()

    assert exc_info.value.code == 1
    error = capsys.readouterr().err
    assert "Missing required packages: structlog" in error
    assert "pip install -r requirements.txt" in error
