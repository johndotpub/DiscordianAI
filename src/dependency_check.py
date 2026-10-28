#!/usr/bin/env python3
"""Early dependency validation to catch missing packages before main startup.

This module runs before any complex imports to ensure all required dependencies
are available, providing clear error messages if packages are missing.

The required set is derived from the third-party modules that ``src`` imports.
Source files are parsed with :mod:`ast` instead of imported, so this check stays
cheap and cannot trigger heavy imports or network access. Imports guarded by a
module-level ``try/except ImportError`` are treated as optional because the code
already handles their absence; lazy imports inside functions are still required.
"""

import ast
import importlib.util
import logging
from pathlib import Path
import sys

_SRC_DIR = Path(__file__).resolve().parent
_IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError"}

# Import names that differ from the distribution users need to install.
_DISTRIBUTION_ALIASES = {
    "bs4": "beautifulsoup4",
    "discord": "discord.py",
}


def _handles_import_error(handlers: list[ast.ExceptHandler]) -> bool:
    """Return whether any handler catches a missing-module error."""
    for handler in handlers:
        if handler.type is None:
            return True
        caught: set[str] = set()
        if isinstance(handler.type, ast.Tuple):
            caught = {item.id for item in handler.type.elts if isinstance(item, ast.Name)}
        elif isinstance(handler.type, ast.Name):
            caught = {handler.type.id}
        if caught & _IMPORT_ERRORS:
            return True
    return False


def _is_type_checking(test: ast.expr) -> bool:
    """Return whether an ``if`` test is ``TYPE_CHECKING``."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


class _RuntimeImportVisitor(ast.NodeVisitor):
    """Collect the third-party modules a source file imports at runtime."""

    def __init__(self) -> None:
        """Initialise the visitor state."""
        self.names: set[str] = set()
        self._function_depth = 0
        self._optional_depth = 0
        self._type_checking_depth = 0

    def _add(self, module: str | None, level: int = 0) -> None:
        """Record a top-level module unless the import is conditional."""
        if level or module is None:
            return
        if self._type_checking_depth or self._optional_depth:
            return
        self.names.add(module.split(".", 1)[0])

    def visit_Import(self, node: ast.Import) -> None:
        """Record ``import ...`` statements."""
        if self._type_checking_depth or self._optional_depth:
            return
        for alias in node.names:
            self._add(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Record absolute ``from ... import ...`` statements."""
        self._add(node.module, node.level)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Visit a function body: lazy imports there are still required."""
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit a regular function."""
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit an async function."""
        self._visit_function(node)

    def visit_If(self, node: ast.If) -> None:
        """Skip imports protected by a ``TYPE_CHECKING`` guard."""
        if not _is_type_checking(node.test):
            self.generic_visit(node)
            return
        self._type_checking_depth += 1
        for child in node.body:
            self.visit(child)
        self._type_checking_depth -= 1
        for child in node.orelse:
            self.visit(child)

    def visit_Try(self, node: ast.Try) -> None:
        """Skip module-level imports whose absence is already handled."""
        optional = self._function_depth == 0 and _handles_import_error(node.handlers)
        if optional:
            self._optional_depth += 1
        for child in node.body:
            self.visit(child)
        if optional:
            self._optional_depth -= 1
        for child in node.handlers:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)
        for child in node.finalbody:
            self.visit(child)


def _collect_imports(tree: ast.AST) -> set[str]:
    """Collect top-level module names imported by an AST at runtime."""
    visitor = _RuntimeImportVisitor()
    visitor.visit(tree)
    return visitor.names


def get_required_imports() -> set[str]:
    """Return the third-party modules imported by the source tree at runtime."""
    local_modules = {path.stem for path in _SRC_DIR.glob("*.py")} | {"src"}
    imported: set[str] = set()
    for path in _SRC_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported.update(_collect_imports(tree))
    return {
        name
        for name in imported
        if name not in sys.stdlib_module_names and name not in local_modules
    }


def required_distributions() -> dict[str, str]:
    """Return a mapping of required import names to distribution names."""
    return {name: _DISTRIBUTION_ALIASES.get(name, name) for name in sorted(get_required_imports())}


def check_dependencies() -> tuple[bool, list[str]]:
    """Check if all required dependencies are available.

    Returns:
        Tuple[bool, List[str]]: (success, list of missing packages)
    """
    missing_packages = []

    for import_name, package_name in required_distributions().items():
        try:
            available = importlib.util.find_spec(import_name) is not None
        except (ImportError, ValueError):
            available = False
        if not available:
            missing_packages.append(package_name)

    return len(missing_packages) == 0, missing_packages


def main():
    """Main entry point for dependency checking."""
    # Set up basic logging for dependency check
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

    success, missing = check_dependencies()

    if not success:
        logger.error("Missing required packages: %s", ", ".join(missing))
        logger.error("Please install dependencies with:")
        logger.error("  pip install -r requirements.txt")
        logger.error("\nOr install individual packages:")
        for package in missing:
            logger.error("  pip install %s", package)
        sys.exit(1)

    logger.info("✓ All dependencies are available.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
