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


def test_markdown_only_changes_still_run_the_ci_jobs():
    """Docs commits must run the docs-truth and changelog guards."""
    workflow = _load_yaml(CI_PATH)
    triggers = workflow.get("on", workflow.get(True))

    for event in ("push", "pull_request"):
        ignored = [str(pattern) for pattern in triggers[event].get("paths-ignore", [])]
        assert "**.md" not in ignored, f"{event} still skips markdown-only changes"
        assert "**/*.md" not in ignored, f"{event} still skips markdown-only changes"


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


def test_ci_runs_the_suite_against_declared_minimum_dependency_versions():
    """A CI job installs lowest-direct runtime deps and runs the suite."""
    workflow = _load_yaml(CI_PATH)
    job = workflow["jobs"]["min-versions"]
    commands = _job_commands(job)

    assert "--resolution lowest-direct" in commands
    assert "-r requirements.txt" in commands
    assert "pytest" in commands
    assert "--timeout=120" in commands


def test_ci_wheel_job_imports_every_installed_src_module():
    """The wheel smoke test must import src.bot, health_server, providers, and routing."""
    workflow = _load_yaml(CI_PATH)
    wheel_commands = _job_commands(workflow["jobs"]["wheel"])

    assert (
        "pkgutil.walk_packages" in wheel_commands
    ), "The wheel smoke job never imports the installed src modules"
    assert "importlib.import_module" in wheel_commands
    assert "sys.exit(1)" in wheel_commands


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


def test_docker_publish_waits_for_a_successful_ci_run():
    """The publish job may not start until CI has passed for this commit."""
    workflow = _load_yaml(DOCKER_PATH)
    jobs = workflow["jobs"]
    gate = jobs["wait-for-ci"]
    publish = jobs["publish"]

    assert publish.get("needs") == "wait-for-ci"
    assert gate.get("timeout-minutes") == 45
    permissions = gate.get("permissions", {}) or {}
    assert permissions.get("actions") == "read"
    assert permissions.get("contents") == "read"
    assert gate.get("env", {}).get("GH_TOKEN") == "${{ github.token }}"
    assert gate.get("env", {}).get("GH_REPO") == "${{ github.repository }}"
    assert "!= 'pull_request'" in str(gate.get("if", ""))

    commands = _job_commands(gate)
    assert "gh run list" in commands
    assert "--workflow ci.yml" in commands
    assert '--commit "$GITHUB_SHA"' in commands
    assert "--json status,conclusion" in commands
    assert "--limit 5" in commands
    assert "sleep 30" in commands
    assert "conclusion" in commands
    assert "within 10 minutes" in commands


def test_docker_wait_for_ci_distinguishes_no_run_from_a_long_run():
    """Only a missing CI run has a ten-minute deadline; a started run may finish."""
    workflow = _load_yaml(DOCKER_PATH)
    commands = _job_commands(workflow["jobs"]["wait-for-ci"])

    assert (
        "no_run_deadline=$((SECONDS + 600))" in commands
    ), "wait-for-ci has no ten-minute deadline for a commit with no CI run"

    no_run = commands.split('if [[ -z "$run" ]]; then', 1)
    assert len(no_run) == 2, "wait-for-ci has no branch for a missing CI run"
    branches = no_run[1].split('elif [[ "$status" != "completed" ]]; then', 1)
    assert (
        len(branches) == 2
    ), "wait-for-ci has no distinct branch for a run that exists but has not completed"
    assert (
        "no_run_deadline" in branches[0]
    ), "the missing-run branch does not enforce the ten-minute deadline"

    pending = branches[1].split("elif ", 1)[0]
    assert "600" not in pending, "the in-progress branch still applies the no-run deadline"
    assert "deadline" not in pending, "the in-progress branch still applies the no-run deadline"


def test_docker_latest_tag_is_limited_to_main_and_version_tags():
    """A dispatch from a feature branch must not overwrite the latest tag."""
    workflow = _load_yaml(DOCKER_PATH)
    publish = workflow["jobs"]["publish"]
    metadata_steps = [
        step
        for step in publish.get("steps", []) or []
        if _action(step).startswith("docker/metadata-action")
    ]
    assert metadata_steps

    for step in metadata_steps:
        tags = str((step.get("with", {}) or {}).get("tags", ""))
        latest_lines = [line for line in tags.splitlines() if "value=latest" in line]
        assert len(latest_lines) == 1, tags
        latest = latest_lines[0]
        assert "enable=" in latest, latest
        assert "refs/heads/main" in latest, latest
        assert "refs/tags/" in latest, latest


def test_docker_publish_is_not_cancelled_mid_run():
    """A newer push may cancel a pull-request build, not a publish run."""
    workflow = _load_yaml(DOCKER_PATH)
    concurrency = workflow.get("concurrency", {}) or {}

    assert "github.event_name == 'pull_request'" in str(concurrency.get("cancel-in-progress", ""))


def test_dockerhub_credentials_are_lifted_to_job_env_and_gate_the_step():
    workflow = _load_yaml(DOCKER_PATH)
    publish = workflow["jobs"]["publish"]
    environment = publish.get("env", {}) or {}
    assert environment.get("DOCKERHUB_USERNAME") == "${{ secrets.DOCKERHUB_USERNAME }}"
    assert environment.get("DOCKERHUB_TOKEN") == "${{ secrets.DOCKERHUB_TOKEN }}"

    login_steps = [
        step
        for step in publish.get("steps", []) or []
        if _action(step).startswith("docker/login-action")
        and (step.get("with", {}) or {}).get("registry") == "docker.io"
    ]
    assert login_steps, "docker.yml has no Docker Hub login step"
    for step in login_steps:
        condition = str(step.get("if", ""))
        assert "env.DOCKERHUB_USERNAME != ''" in condition
        assert "env.DOCKERHUB_TOKEN != ''" in condition


def test_no_workflow_step_condition_references_the_secrets_context():
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows

    offenders = []
    for path in workflows:
        workflow = _load_yaml(path)
        for job_name, job in workflow.get("jobs", {}).items():
            for index, step in enumerate(job.get("steps", []) or []):
                condition = step.get("if")
                if condition is not None and "secrets." in str(condition):
                    offenders.append(f"{path.name}:{job_name}:steps[{index}]")

    assert not offenders, (
        "the secrets context is unavailable in steps[*].if; lift it into job-level env: "
        f"{offenders}"
    )


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
        with_options = step.get("with", {}) or {}
        assert with_options.get("fail_ci_if_error") is True
        assert with_options.get("files") == "coverage.xml"
        assert "file" not in with_options


def test_coverage_upload_skips_when_token_is_unavailable():
    workflow = _load_yaml(CI_PATH)
    test_job = workflow["jobs"]["test"]
    token_check = next(step for step in test_job["steps"] if step.get("id") == "codecov-token")
    upload = next(
        step for step in test_job["steps"] if _action(step).startswith("codecov/codecov-action")
    )

    assert "secrets." in token_check["env"].get("CODECOV_TOKEN", "")
    assert "available=false" in token_check["run"]
    assert "steps.codecov-token.outputs.available == 'true'" in upload["if"]


def test_local_config_names_are_git_ignored():
    git = which("git")
    assert git is not None

    names = ("bot.ini", "production.ini", "config.ini")
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
