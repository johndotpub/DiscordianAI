"""Tests for the startup dependency gate.

The gate must reflect what ``src`` actually imports at runtime. These tests
compute that set independently from the source tree so a new third-party import
cannot silently go unchecked.
"""

import ast
import importlib.util
import logging
from pathlib import Path
import sys

import pytest

from src import dependency_check as gate

SRC_DIR = Path(gate.__file__).resolve().parent
IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError"}


def _handles_import_error(handlers: list[ast.ExceptHandler]) -> bool:
    for handler in handlers:
        if handler.type is None:
            return True
        caught: set[str] = set()
        if isinstance(handler.type, ast.Tuple):
            caught = {item.id for item in handler.type.elts if isinstance(item, ast.Name)}
        elif isinstance(handler.type, ast.Name):
            caught = {handler.type.id}
        if caught & IMPORT_ERRORS:
            return True
    return False


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _collect_imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()

    def walk(  # noqa: PLR0912
        node: ast.AST, function_depth: int, optional_depth: int, type_checking: int
    ):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.iter_child_nodes(node):
                walk(child, function_depth + 1, optional_depth, type_checking)
            return
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            for child in node.body:
                walk(child, function_depth, optional_depth, type_checking + 1)
            for child in node.orelse:
                walk(child, function_depth, optional_depth, type_checking)
            return
        if isinstance(node, ast.Try):
            optional = function_depth == 0 and _handles_import_error(node.handlers)
            for child in node.body:
                walk(child, function_depth, optional_depth + int(optional), type_checking)
            for child in node.handlers:
                walk(child, function_depth, optional_depth, type_checking)
            for child in node.orelse:
                walk(child, function_depth, optional_depth, type_checking)
            for child in node.finalbody:
                walk(child, function_depth, optional_depth, type_checking)
            return
        if isinstance(node, ast.Import):
            if not type_checking and not optional_depth:
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and (
            not type_checking
            and not optional_depth
            and node.level == 0
            and node.module is not None
        ):
            names.add(node.module.split(".", 1)[0])
        for child in ast.iter_child_nodes(node):
            walk(child, function_depth, optional_depth, type_checking)

    walk(tree, 0, 0, 0)
    return names


def _third_party_imports_in_src() -> set[str]:
    local_modules = {path.stem for path in SRC_DIR.glob("*.py")} | {"src"}
    imported: set[str] = set()
    for path in SRC_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported.update(_collect_imports(tree))
    return {
        name
        for name in imported
        if name not in sys.stdlib_module_names and name not in local_modules
    }


def _find_spec_without(*missing: str):
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name in missing:
            return None
        return real_find_spec(name, *args, **kwargs)

    return fake_find_spec


def test_checked_set_matches_imports_in_src() -> None:
    """Every third-party runtime import is checked, and nothing else."""
    assert gate.get_required_imports() == _third_party_imports_in_src()


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


def test_satisfied_environment_passes() -> None:
    """The test environment has every required dependency installed."""
    success, missing = gate.check_dependencies()
    assert success is True
    assert missing == []
