"""Contract tests for changelog release entries and version parity."""

from pathlib import Path
import re
import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

RELEASE_HEADING = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)


def _changelog_text() -> str:
    return CHANGELOG_PATH.read_text(encoding="utf-8")


def _pyproject_version() -> str:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    return data["project"]["version"]


def _released_versions(text: str) -> list[str]:
    versions = RELEASE_HEADING.findall(text)
    return [version for version in versions if version.lower() != "unreleased"]


def _entry(text: str, version: str) -> str:
    match = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"CHANGELOG.md has no entry for {version}"
    return match.group(1)


def test_top_released_version_matches_pyproject():
    """The newest released changelog version equals the project version."""
    versions = _released_versions(_changelog_text())

    assert versions, "CHANGELOG.md has no released versions"
    assert versions[0] == _pyproject_version()


def test_no_unreleased_section_remains():
    """Every change belongs to a released entry, so no Unreleased heading remains."""
    assert not re.search(r"^## \[Unreleased\]", _changelog_text(), re.MULTILINE)


def test_current_entry_has_behaviour_changes_section():
    """The current release describes user-visible behaviour changes."""
    entry = _entry(_changelog_text(), _pyproject_version())

    assert re.search(r"^### Behaviour changes\s*$", entry, re.MULTILINE)
