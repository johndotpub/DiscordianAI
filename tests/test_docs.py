"""Tests for documentation integrity."""

import importlib
from pathlib import Path
import re

AUTOMODULE_PATTERN = re.compile(r"\.\.\s+automodule::\s+(src\.[A-Za-z0-9_]+)")
DOCS_API_DIR = Path(__file__).resolve().parents[1] / "docs" / "api"


def test_docs_api_automodule_targets_are_importable():
    """Ensure docs API autodoc targets still exist in src."""

    rst_files = sorted(DOCS_API_DIR.glob("*.rst"))
    assert rst_files, "No .rst files found under docs/api/"

    for rst_file in rst_files:
        content = rst_file.read_text(encoding="utf-8")
        modules = AUTOMODULE_PATTERN.findall(content)
        if not modules:
            continue

        for module_name in modules:
            importlib.import_module(module_name)
