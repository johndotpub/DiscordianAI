"""Tests for documentation integrity."""

import importlib
import importlib.util
from pathlib import Path
import re
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTOMODULE_PATTERN = re.compile(r"\.\.\s+automodule::\s+(src\.[A-Za-z0-9_]+)")
TOCTREE_ENTRY_PATTERN = re.compile(r"^\s{3,}([A-Za-z0-9_]+)\s*$", re.MULTILINE)
DOCS_API_DIR = REPO_ROOT / "docs" / "api"
INDEX_RST = DOCS_API_DIR / "index.rst"


def source_modules() -> set[str]:
    """Return importable module stems under src/ excluding the package initializer."""
    return {path.stem for path in (REPO_ROOT / "src").glob("*.py") if path.stem != "__init__"}


def api_doc_modules() -> set[str]:
    """Return module stems that have a page under docs/api/."""
    return {path.stem for path in DOCS_API_DIR.glob("*.rst") if path.stem != "index"}


def toctree_entries() -> set[str]:
    """Return document names listed in the docs/api/index.rst toctrees."""
    return set(TOCTREE_ENTRY_PATTERN.findall(INDEX_RST.read_text(encoding="utf-8")))


def missing_api_pages() -> list[str]:
    """Return source modules without a matching API reference page."""
    return sorted(source_modules() - api_doc_modules())


def missing_toctree_entries() -> list[str]:
    """Return API pages that are missing from the index toctree."""
    return sorted(api_doc_modules() - toctree_entries())


def unknown_toctree_entries() -> list[str]:
    """Return index toctree entries that have no matching .rst page."""
    return sorted(toctree_entries() - api_doc_modules())


def automodule_targets() -> list[tuple[Path, str]]:
    """Return every automodule target and the file that declares it."""
    targets: list[tuple[Path, str]] = []
    for rst_file in sorted(DOCS_API_DIR.glob("*.rst")):
        content = rst_file.read_text(encoding="utf-8")
        targets.extend((rst_file, module) for module in AUTOMODULE_PATTERN.findall(content))
    return targets


def test_docs_api_automodule_targets_are_importable():
    """Ensure docs API autodoc targets still exist in src."""
    targets = automodule_targets()
    assert targets, "No automodule targets found under docs/api/"

    for rst_file, module_name in targets:
        try:
            importlib.import_module(module_name)
        except ImportError as exc:
            location = rst_file.relative_to(REPO_ROOT)
            pytest.fail(f"{location} targets missing module {module_name}: {exc}")


def test_docs_every_source_module_has_api_page():
    """Every src/ module has a matching docs/api/<module>.rst page."""
    missing = missing_api_pages()
    assert not missing, "Missing API pages for: " + ", ".join(f"src/{name}.py" for name in missing)


def test_docs_every_api_page_is_in_a_toctree():
    """Every docs/api/*.rst page is reachable from index.rst."""
    missing = missing_toctree_entries()
    unknown = unknown_toctree_entries()
    assert not missing, "API pages missing from index.rst: " + ", ".join(missing)
    assert not unknown, "index.rst references missing pages: " + ", ".join(unknown)


@pytest.mark.skipif(
    importlib.util.find_spec("sphinx") is None or importlib.util.find_spec("furo") is None,
    reason="Sphinx or the furo theme is not installed",
)
def test_docs_sphinx_build_is_warning_free(tmp_path):
    """The Sphinx HTML build succeeds with warnings treated as errors."""
    build_dir = tmp_path / "html"
    result = subprocess.run(  # noqa: S603 - fixed interpreter and local docs path, no shell
        [
            sys.executable,
            "-m",
            "sphinx",
            "-b",
            "html",
            str(DOCS_API_DIR),
            str(build_dir),
            "-W",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
