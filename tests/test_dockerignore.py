"""Guardrails for the Docker build context exclusions."""

from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"


def _patterns() -> list[str]:
    """Return non-comment lines from .dockerignore in file order."""
    return [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _matches(path: str, pattern: str) -> bool:
    """Return True when a Dockerignore pattern matches a relative path."""
    pattern = pattern.rstrip("/")
    return fnmatch(path, pattern) or path.startswith(f"{pattern}/")


def _is_excluded(path: str, patterns: list[str]) -> bool:
    """Apply Dockerignore patterns in order, honouring negations."""
    excluded = False
    for pattern in patterns:
        if pattern.startswith("!"):
            if _matches(path, pattern[1:]):
                excluded = False
        elif _matches(path, pattern):
            excluded = True
    return excluded


def test_dockerignore_excludes_local_config_and_caches():
    """Private configs, runtime state, and tool caches stay out of the image."""
    patterns = _patterns()

    assert "bender.ini" in patterns
    assert "config.ini" in patterns
    assert "*.ini" in patterns
    assert "!config.ini.example" in patterns
    assert "!tox.ini" in patterns

    for path in (
        "bender.ini",
        "config.ini",
        ".bot.pid",
        ".pytest_cache/v/cache",
        ".ruff_cache/content",
        ".mypy_cache/3.12",
        ".hermes/state",
        "htmlcov/index.html",
        "coverage.xml",
    ):
        assert _is_excluded(path, patterns), f"{path} must not enter the build context"


def test_dockerignore_keeps_build_inputs():
    """The package source and packaging metadata remain in the build context."""
    patterns = _patterns()

    for path in (
        "src/main.py",
        "pyproject.toml",
        "requirements.txt",
        "config.ini.example",
        "tox.ini",
    ):
        assert not _is_excluded(path, patterns), f"{path} must remain buildable"
