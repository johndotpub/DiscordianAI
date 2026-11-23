"""Contract tests for the curated mutation checker."""

import importlib.util
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
MUTATION_SCRIPT = REPO_ROOT / "scripts" / "mutation_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mutation_check_under_test", MUTATION_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_mutation_anchor_matches_the_current_source():
    """A stale snippet would report INVALID instead of testing the guard."""
    module = _load_module()
    stale = []

    for mutation in module.MUTATIONS:
        source = (REPO_ROOT / mutation.path).read_text(encoding="utf-8")
        _old, _new, occurrences = module._match_snippet(source, mutation.old, mutation.new)
        if occurrences != 1:
            stale.append(f"{mutation.name}: {occurrences} matches in {mutation.path}")

    assert not stale, f"Stale mutation anchors: {stale}"


def test_workspace_copy_excludes_vcs_caches_and_local_config(tmp_path):
    """Mutations must never touch the real checkout or copy local secrets."""
    module = _load_module()
    source = tmp_path / "source"
    (source / "src").mkdir(parents=True)
    (source / "src" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("secret", encoding="utf-8")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "main.pyc").write_bytes(b"cache")
    (source / ".venv").mkdir()
    (source / "config.ini.example").write_text("[Discord]\n", encoding="utf-8")
    (source / "tox.ini").write_text("[tox]\n", encoding="utf-8")
    (source / "bot.ini").write_text("DISCORD_TOKEN=local\n", encoding="utf-8")
    (source / ".env").write_text("DISCORD_TOKEN=local\n", encoding="utf-8")
    (source / "bot.log-2026-10-30.gz").write_bytes(b"log")

    destination = tmp_path / "copy"
    module._copy_workspace(source, destination)

    assert (destination / "src" / "main.py").is_file()
    assert (destination / "config.ini.example").is_file()
    assert (destination / "tox.ini").is_file()
    for excluded in (".git", "__pycache__", ".venv", "bot.ini", ".env", "bot.log-2026-10-30.gz"):
        assert not (destination / excluded).exists(), f"{excluded} entered the scratch copy"
