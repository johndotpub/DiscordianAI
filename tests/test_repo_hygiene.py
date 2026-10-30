"""Contract tests for repository hygiene and release metadata."""

from importlib import metadata
from pathlib import Path
import re
from shutil import which
import subprocess
import tomllib

from src import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
LOGROTATE_PATH = REPO_ROOT / "contrib" / "logrotate" / "discordianai"
DAEMON_DOC_PATH = REPO_ROOT / "docs" / "Daemon.md"

ARTIFACT_PATTERNS = (
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"(^|/)build/"),
    re.compile(r"(^|/)tmp/"),
    re.compile(r"(^|/)\.coverage[^/]*$"),
    re.compile(r"(^|/)[^/]+\.egg-info/"),
    re.compile(r"\.log$"),
)

LOGROTATE_REQUIRED_DIRECTIVES = (
    "size",
    "rotate",
    "compress",
    "missingok",
    "notifempty",
    "copytruncate",
)


def _tracked_paths():
    git = which("git")
    assert git is not None
    result = subprocess.run(  # noqa: S603 — fixed git command, no shell
        [git, "-C", str(REPO_ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [path for path in result.stdout.split("\0") if path]


def _pyproject_version():
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    return data["project"]["version"]


def _installed_version():
    try:
        return metadata.version("DiscordianAI")
    except metadata.PackageNotFoundError:
        return None


def test_ruff_errors_dump_is_absent_and_untracked():
    assert not (REPO_ROOT / "ruff_errors.txt").exists()
    assert "ruff_errors.txt" not in _tracked_paths()


def test_package_version_matches_pyproject():
    pyproject_version = _pyproject_version()
    installed_version = _installed_version()

    if installed_version is not None:
        assert installed_version == pyproject_version
    assert __version__ == pyproject_version


def test_no_tracked_build_or_cache_artifacts():
    offenders = [
        path
        for path in _tracked_paths()
        if any(pattern.search(path) for pattern in ARTIFACT_PATTERNS)
    ]
    assert not offenders, f"Tracked build or cache artifacts: {offenders}"


def test_logrotate_fragment_is_shipped_and_complete():
    assert LOGROTATE_PATH.is_file()
    text = LOGROTATE_PATH.read_text(encoding="utf-8")

    for directive in LOGROTATE_REQUIRED_DIRECTIVES:
        assert re.search(
            rf"^\s*{directive}\b", text, re.MULTILINE
        ), f"Missing '{directive}' directive"
    assert re.search(r"^\s*size\s+\S+", text, re.MULTILINE)
    assert re.search(r"^\s*rotate\s+\d+", text, re.MULTILINE)


def test_daemon_docs_document_installation_and_copytruncate_caveat():
    text = DAEMON_DOC_PATH.read_text(encoding="utf-8")

    assert "contrib/logrotate/discordianai" in text
    assert "/etc/logrotate.d/discordianai" in text
    assert "copytruncate" in text
    assert re.search(r"copytruncate[^.]*(?:caveat|race|truncat)", text, re.IGNORECASE)
