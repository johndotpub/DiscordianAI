"""Guardrails that keep tracked text files on LF line endings."""

from pathlib import Path
from shutil import which
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]

TEXT_EXTENSIONS = {
    ".sh",
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".rst",
    ".json",
}
TEXT_FILENAMES = {"Dockerfile"}


def _is_text_path(path: str) -> bool:
    """Return whether *path* names a file governed by the text rules."""
    return Path(path).name in TEXT_FILENAMES or Path(path).suffix in TEXT_EXTENSIONS


def _tracked_eol_entries() -> list[tuple[str, str, str]]:
    """Return ``(path, index_eol, worktree_eol)`` for every tracked file."""
    git = which("git")
    assert git is not None
    result = subprocess.run(  # noqa: S603 - fixed git command, no shell
        [git, "ls-files", "--eol", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    entries: list[tuple[str, str, str]] = []
    for record in result.stdout.split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        fields = metadata.split()
        entries.append((path, fields[0], fields[1]))
    return entries


def test_tracked_text_files_have_no_crlf_in_the_working_tree():
    """Catch text files checked out with CRLF despite the attributes."""
    offenders = [
        path
        for path, _index_eol, worktree_eol in _tracked_eol_entries()
        if _is_text_path(path) and worktree_eol in {"crlf", "mixed"}
    ]
    assert offenders == []


def test_tracked_text_files_are_normalised_in_the_index():
    """Catch text blobs staged with CRLF despite the attributes."""
    offenders = [
        path
        for path, index_eol, _worktree_eol in _tracked_eol_entries()
        if _is_text_path(path) and index_eol in {"crlf", "mixed"}
    ]
    assert offenders == []


def test_gitattributes_exists_with_text_auto_default():
    """Keep the repository-wide normalisation rule in place."""
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    rules = {line.strip() for line in attributes.splitlines()}
    assert "* text=auto eol=lf" in rules
