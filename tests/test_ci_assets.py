"""Contract tests for CI workflows, scanning config, and local gate script."""

import os
from pathlib import Path
from shutil import which
import subprocess

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DOCKER_PATH = REPO_ROOT / ".github" / "workflows" / "docker.yml"
CODEQL_PATH = REPO_ROOT / ".github" / "codeql" / "codeql-config.yml"
PREFLIGHT_PATH = REPO_ROOT / "scripts" / "preflight.sh"

CLEAR_TEXT_QUERY = "py/clear-text-logging-sensitive-data"


def _load_yaml(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _job_commands(job):
    commands = []
    for step in job.get("steps", []) or []:
        run = step.get("run")
        if run:
            commands.append(str(run))
    return "\n".join(commands)


def _action(step):
    return str(step.get("uses", ""))


def _all_steps(workflow):
    return [step for job in workflow["jobs"].values() for step in job.get("steps", []) or []]


def _build_steps(workflow):
    return [
        step
        for step in _all_steps(workflow)
        if _action(step).startswith("docker/build-push-action")
    ]


def _push_enabled(step):
    value = (step.get("with", {}) or {}).get("push", True)
    return not (value is False or str(value).strip().lower() == "false")


def _registry_markers(tags):
    text = str(tags).lower()
    markers = set()
    if "ghcr" in text or "meta-ghcr" in text:
        markers.add("ghcr")
    if "dockerhub" in text or "docker.io" in text or "meta-dockerhub" in text:
        markers.add("dockerhub")
    return markers


def test_ci_installs_a_built_wheel_and_runs_console_script():
    workflow = _load_yaml(CI_PATH)
    matching = []

    for name, job in workflow["jobs"].items():
        commands = _job_commands(job)
        if (
            "build --wheel" in commands
            and "dist/*.whl" in commands
            and "discordianai --help" in commands
            and "src.main --help" in commands
            and "zipfile" in commands
            and "src/" in commands
        ):
            matching.append(name)

    assert matching, (
        "No CI job builds a wheel, verifies it ships a src/ package, installs it, "
        "and runs the console script"
    )


def test_docker_workflow_has_qemu_pr_build_and_split_registry_pushes():
    workflow = _load_yaml(DOCKER_PATH)
    triggers = workflow.get("on", workflow.get(True))
    assert "pull_request" in triggers

    actions = [_action(step) for step in _all_steps(workflow)]
    qemu_indexes = [
        index
        for index, action in enumerate(actions)
        if action.startswith("docker/setup-qemu-action")
    ]
    buildx_indexes = [
        index
        for index, action in enumerate(actions)
        if action.startswith("docker/setup-buildx-action")
    ]
    assert qemu_indexes, "docker.yml does not register binfmt with setup-qemu-action"
    assert buildx_indexes, "docker.yml has no setup-buildx-action"
    assert min(qemu_indexes) < min(buildx_indexes), "QEMU must be set up before buildx"

    pr_build_jobs = []
    for name, job in workflow["jobs"].items():
        condition = str(job.get("if", "")).replace('"', "'")
        steps = [
            step
            for step in job.get("steps", []) or []
            if _action(step).startswith("docker/build-push-action")
        ]
        if "== 'pull_request'" in condition and steps:
            assert all(not _push_enabled(step) for step in steps)
            pr_build_jobs.append(name)
    assert pr_build_jobs, "docker.yml has no pull-request job that builds without pushing"

    pushed_registries = set()
    for step in _build_steps(workflow):
        with_options = step.get("with", {}) or {}
        assert with_options.get("provenance") is True
        if not _push_enabled(step):
            continue
        markers = _registry_markers(with_options.get("tags", ""))
        assert (
            len(markers) <= 1
        ), "A single unconditional build step pushes to both GHCR and Docker Hub"
        pushed_registries |= markers

    assert pushed_registries == {"ghcr", "dockerhub"}


def test_codeql_clear_text_logging_filter_is_scoped_or_removed():
    config = _load_yaml(CODEQL_PATH)
    filters = config.get("query-filters", []) or []

    for item in filters:
        exclude = item.get("exclude", {}) or {}
        if exclude.get("id") != CLEAR_TEXT_QUERY:
            continue
        scoped_paths = exclude.get("paths") or exclude.get("path") or item.get("paths")
        assert (
            scoped_paths
        ), f"{CLEAR_TEXT_QUERY} is excluded repository-wide instead of at a call site"


def test_coverage_upload_failure_is_visible():
    workflow = _load_yaml(CI_PATH)
    codecov_steps = [
        step for step in _all_steps(workflow) if _action(step).startswith("codecov/codecov-action")
    ]
    assert codecov_steps, "CI does not upload coverage to Codecov"

    for step in codecov_steps:
        assert step.get("continue-on-error") is not True
        assert (step.get("with", {}) or {}).get("fail_ci_if_error") is True


def test_local_config_names_are_git_ignored():
    git = which("git")
    assert git is not None

    names = ("bot.ini", "production.ini", "bender.ini", "config.ini")
    missing = []
    for name in names:
        result = subprocess.run(  # noqa: S603 - fixed git command, no shell
            [git, "-C", str(REPO_ROOT), "check-ignore", "-q", "--no-index", name],
            check=False,
        )
        if result.returncode != 0:
            missing.append(name)

    assert not missing, f"Local config files that can still be committed: {missing}"


def test_preflight_script_exists_and_is_executable():
    assert PREFLIGHT_PATH.is_file(), "scripts/preflight.sh is missing"
    assert os.access(PREFLIGHT_PATH, os.X_OK), "scripts/preflight.sh is not executable"

    commands = PREFLIGHT_PATH.read_text(encoding="utf-8").lower()
    for gate in ("black", "ruff", "pytest", "sphinx", "build"):
        assert gate in commands, f"scripts/preflight.sh does not run {gate}"
