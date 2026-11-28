"""Contract tests for the curated mutation checker."""

import importlib.util
from pathlib import Path
import sys

import pytest

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


def _sample_workspace(tmp_path, module):
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    mutation = module.Mutation(
        name="sample-mutation",
        path="src/sample.py",
        test="tests/test_sample.py",
        old="VALUE = 1",
        new="VALUE = 2",
    )
    return workspace, mutation


def _run_one(module, tmp_path, mutant_run):
    workspace, mutation = _sample_workspace(tmp_path, module)
    runs = iter(
        [
            module.TestRun(0, "1 passed", "1 passed in 0.10s"),
            mutant_run,
        ]
    )

    def fake_runner(_root, _test_paths, _timeout):
        return next(runs)

    return module._run_selected(workspace, [mutation], 5.0, fake_runner)


def test_a_failing_baseline_aborts_before_any_mutation(tmp_path):
    """A broken unmutated copy must not make every mutant look killed."""
    module = _load_module()
    workspace, mutation = _sample_workspace(tmp_path, module)
    calls = []

    def fake_runner(_root, test_paths, _timeout):
        calls.append(list(test_paths))
        return module.TestRun(1, "1 failed in 0.10s", "1 failed in 0.10s")

    with pytest.raises(module.BaselineFailure, match="1 failed"):
        module._run_selected(workspace, [mutation], 5.0, fake_runner)

    assert calls == [["tests/test_sample.py"]]
    assert (workspace / "src" / "sample.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_exit_two_is_inconclusive_and_fails_the_check(tmp_path):
    """A collection or internal error is not evidence that the mutant died."""
    module = _load_module()

    results = _run_one(
        module,
        tmp_path,
        module.TestRun(2, "pytest interrupted", "pytest interrupted"),
    )

    assert results[0].status == "INCONCLUSIVE"
    assert "2" in results[0].detail
    assert module._failure_exit_code(results) == 1


def test_exit_one_with_a_failed_test_is_killed(tmp_path):
    """One failed test is the only passing evidence for a mutation."""
    module = _load_module()

    results = _run_one(
        module,
        tmp_path,
        module.TestRun(1, "1 failed, 0 passed in 0.10s", "1 failed, 0 passed in 0.10s"),
    )

    assert results[0].status == "KILLED"
    assert module._failure_exit_code(results) == 0


def test_exit_zero_is_survived(tmp_path):
    """A green mutant run means the tests did not catch the change."""
    module = _load_module()

    results = _run_one(
        module,
        tmp_path,
        module.TestRun(0, "1 passed in 0.10s", "1 passed in 0.10s"),
    )

    assert results[0].status == "SURVIVED"
    assert module._failure_exit_code(results) == 1
