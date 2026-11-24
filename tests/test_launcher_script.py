"""Bash-level tests for the launcher's process-management helpers."""

import os
from pathlib import Path
import shutil
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "discordian.sh"
LIBRARY_PATH = REPO_ROOT / "scripts" / "launcher_lib.sh"
BASH_PATH = shutil.which("bash") or "/bin/bash"
PS_PATH = shutil.which("ps") or "/bin/ps"


def _run_bash(
    script: str,
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed bash executable, no shell
        [BASH_PATH, "-c", script, "launcher-test", *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env={
            **os.environ,
            "LAUNCHER_LIB": str(LIBRARY_PATH),
            **(env or {}),
        },
    )


def _start_fake_bot(config_arg: str, cwd: Path) -> subprocess.Popen[bytes]:
    """Start a sleeping process whose command line looks like the bot's."""
    process = subprocess.Popen(  # noqa: S603 - fixed bash and sleep executables
        [
            BASH_PATH,
            "-c",
            'exec -a "$1" /bin/sleep 30',
            "fake-bot",
            f"python -m src.main --conf {config_arg}",
        ],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(500):
        if "src.main" in _process_args(process.pid):
            return process
        os.sched_yield()
    process.kill()
    process.wait(timeout=5)
    msg = "fake bot process did not exec"
    raise AssertionError(msg)


def _process_args(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        completed = subprocess.run(  # noqa: S603 - fixed ps executable
            [PS_PATH, "-o", "args=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return completed.stdout
    return raw.replace(b"\0", b" ").decode()


def _assert_stopped(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        msg = "process was not stopped"
        raise AssertionError(msg) from None


def _instance_pid_file(project: Path, config_file: str) -> Path:
    script = """
set -euo pipefail
source "$LAUNCHER_LIB"
instance_pid_file "$1" "$2"
"""
    completed = _run_bash(script, str(project), config_file)
    assert completed.returncode == 0, completed.stderr
    return Path(completed.stdout.strip())


def _stop_instance(project: Path, config_file: str) -> subprocess.CompletedProcess[str]:
    script = """
set -euo pipefail
source "$LAUNCHER_LIB"
log() { :; }
stop_pid_file_instance "$(instance_pid_file "$1" "$2")"
"""
    return _run_bash(script, str(project), config_file)


def test_wait_for_exit_does_not_abort_under_set_e():
    """The post-increment of zero used to exit the launcher on the first second."""
    script = """
set -euo pipefail
source "$LAUNCHER_LIB"
/bin/sleep 30 >/dev/null 2>&1 &
target=$!
sleep() { :; }
wait_for_exit "$target" 2
kill -0 "$target" 2>/dev/null || exit 3
kill -9 "$target" 2>/dev/null || true
wait "$target" 2>/dev/null || true
echo survived
"""

    completed = _run_bash(script)

    assert completed.returncode == 0, completed.stderr
    assert "survived" in completed.stdout


def test_stop_pid_file_removes_the_file_even_after_a_wait(tmp_path):
    """A restarted instance must not leave a stale .bot.pid behind."""
    pid_file = tmp_path / ".bot.pid"
    script = """
set -euo pipefail
source "$LAUNCHER_LIB"
log() { :; }
pid_file="$1"
/bin/sleep 30 >/dev/null 2>&1 &
target=$!
echo "$target" > "$pid_file"
sleep() { :; }
stop_pid_file_instance "$pid_file"
[[ ! -e "$pid_file" ]] || exit 4
wait "$target" 2>/dev/null || true
if kill -0 "$target" 2>/dev/null; then
    kill -9 "$target" 2>/dev/null || true
    exit 5
fi
echo cleaned
"""

    completed = _run_bash(script, str(pid_file))

    assert completed.returncode == 0, completed.stderr
    assert "cleaned" in completed.stdout
    assert not pid_file.exists()


def test_two_configs_keep_separate_instances(tmp_path):
    """Starting prod.ini must not stop the bot.ini instance; bot.ini restarts itself."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "bot.ini").write_text("", encoding="utf-8")
    (project / "prod.ini").write_text("", encoding="utf-8")

    bot = _start_fake_bot("bot.ini", project)
    prod = _start_fake_bot("prod.ini", project)
    try:
        bot_pid_file = _instance_pid_file(project, "bot.ini")
        prod_pid_file = _instance_pid_file(project, "prod.ini")
        assert bot_pid_file.name == ".bot-bot.pid"
        assert prod_pid_file.name == ".bot-prod.pid"
        assert bot_pid_file != prod_pid_file
        bot_pid_file.write_text(f"{bot.pid}\n", encoding="utf-8")
        prod_pid_file.write_text(f"{prod.pid}\n", encoding="utf-8")

        completed = _stop_instance(project, "prod.ini")

        assert completed.returncode == 0, completed.stderr
        _assert_stopped(prod)
        assert bot.poll() is None
        assert bot_pid_file.exists(), "starting prod.ini removed bot.ini's PID file"
        assert bot_pid_file.read_text(encoding="utf-8") == f"{bot.pid}\n"
        assert not prod_pid_file.exists()

        completed = _stop_instance(project, "bot.ini")

        assert completed.returncode == 0, completed.stderr
        _assert_stopped(bot)
        assert not bot_pid_file.exists()
    finally:
        for process in (bot, prod):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_straggler_lookup_matches_only_the_same_checkout(tmp_path):
    """Two checkouts that both use bot.ini must not match each other's process."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    for project in (first, second):
        project.mkdir()
        (project / "bot.ini").write_text("", encoding="utf-8")

    first_bot = _start_fake_bot("bot.ini", first)
    second_bot = _start_fake_bot("bot.ini", second)
    try:
        script = """
set -euo pipefail
source "$LAUNCHER_LIB"
straggler_pids "bot.ini"
"""
        completed = _run_bash(script, cwd=first)

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.split() == [str(first_bot.pid)]
        assert second_bot.poll() is None
    finally:
        for process in (first_bot, second_bot):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_legacy_pid_file_is_used_for_the_same_config(tmp_path):
    """An upgrade must stop the instance recorded in the shared legacy file."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "bot.ini").write_text("", encoding="utf-8")
    bot = _start_fake_bot("bot.ini", project)
    legacy = project / ".bot.pid"
    legacy.write_text(f"{bot.pid}\n", encoding="utf-8")
    try:
        script = """
set -euo pipefail
source "$LAUNCHER_LIB"
log() { :; }
stop_legacy_pid_file_instance "$1" "$2"
"""
        completed = _run_bash(script, str(legacy), str(project / "bot.ini"))

        assert completed.returncode == 0, completed.stderr
        _assert_stopped(bot)
        assert not legacy.exists()
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


def test_legacy_pid_file_for_another_config_is_left_alone(tmp_path):
    """The shared file may belong to a different config; it must not be touched."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "bot.ini").write_text("", encoding="utf-8")
    (project / "other.ini").write_text("", encoding="utf-8")
    other = _start_fake_bot("other.ini", project)
    legacy = project / ".bot.pid"
    legacy.write_text(f"{other.pid}\n", encoding="utf-8")
    try:
        script = """
set -euo pipefail
source "$LAUNCHER_LIB"
log() { :; }
stop_legacy_pid_file_instance "$1" "$2"
"""
        completed = _run_bash(script, str(legacy), str(project / "bot.ini"))

        assert completed.returncode == 0, completed.stderr
        assert other.poll() is None
        assert legacy.read_text(encoding="utf-8") == f"{other.pid}\n"
    finally:
        if other.poll() is None:
            other.kill()
            other.wait(timeout=5)


def test_install_systemd_enables_then_starts_the_unit():
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    enable = text.index('systemctl --user enable "${UNIT_NAME}"')
    start = text.index('systemctl --user start "${UNIT_NAME}"')

    assert enable < start
    assert "scripts/launcher_lib.sh" in text
    assert LIBRARY_PATH.is_file()
