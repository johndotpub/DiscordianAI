"""Bash-level tests for the launcher's process-management helpers."""

import os
from pathlib import Path
import shutil
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "discordian.sh"
LIBRARY_PATH = REPO_ROOT / "scripts" / "launcher_lib.sh"
BASH_PATH = shutil.which("bash") or "/bin/bash"


def _run_bash(
    script: str,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed bash executable, no shell
        [BASH_PATH, "-c", script, "launcher-test", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env={**os.environ, **(env or {})},
    )


def test_wait_for_exit_does_not_abort_under_set_e():
    """The post-increment of zero used to exit the launcher on the first second."""
    script = """
set -euo pipefail
source scripts/launcher_lib.sh
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
source scripts/launcher_lib.sh
log() { :; }
pid_file="$1"
/bin/sleep 30 >/dev/null 2>&1 &
target=$!
echo "$target" > "$pid_file"
sleep() { :; }
stop_pid_file_instance "$pid_file"
[[ ! -e "$pid_file" ]] || exit 4
if kill -0 "$target" 2>/dev/null; then
    kill -9 "$target" 2>/dev/null || true
    exit 5
fi
wait "$target" 2>/dev/null || true
echo cleaned
"""

    completed = _run_bash(script, str(pid_file))

    assert completed.returncode == 0, completed.stderr
    assert "cleaned" in completed.stdout
    assert not pid_file.exists()


def test_straggler_lookup_is_scoped_to_one_config(tmp_path):
    """A different config's instance is a different service and is not matched."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_pgrep = fake_bin / "pgrep"
    fake_pgrep.write_text(
        """#!/usr/bin/env bash
pattern="${@: -1}"
grep -E "$pattern" "$PGREP_FIXTURES" | cut -d' ' -f1
""",
        encoding="utf-8",
    )
    fake_pgrep.chmod(0o755)
    fixtures = tmp_path / "processes.txt"
    fixtures.write_text(
        "1234 python -m src.main --conf alpha.ini\n"
        "5678 python -m src.main --conf beta.ini\n"
        "9012 python -m src.main --conf alpha.ini.bak\n",
        encoding="utf-8",
    )

    script = """
set -euo pipefail
source scripts/launcher_lib.sh
straggler_pids "$1"
"""
    completed = _run_bash(
        script,
        "alpha.ini",
        env={
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "PGREP_FIXTURES": str(fixtures),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split() == ["1234"]


def test_install_systemd_enables_then_starts_the_unit():
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    enable = text.index('systemctl --user enable "${UNIT_NAME}"')
    start = text.index('systemctl --user start "${UNIT_NAME}"')

    assert enable < start
    assert "scripts/launcher_lib.sh" in text
    assert LIBRARY_PATH.is_file()
