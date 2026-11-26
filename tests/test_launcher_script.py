"""Bash-level tests for the launcher's process-management helpers."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

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
            "DISCORDIANAI_STOP_TIMEOUT": "0",
            **(env or {}),
        },
    )


def _start_fake_bot(config_arg: str, cwd: Path) -> subprocess.Popen[bytes]:
    """Start a sleeping process whose argv looks like the bot's."""
    process = subprocess.Popen(  # noqa: S603 - fixed bash and Python executables
        [
            BASH_PATH,
            "-c",
            'exec -a "$1" "$2" -c "import time; time.sleep(30)" "$3" "$4" "$5"',
            "fake-bot",
            f"python -m src.main --conf {config_arg}",
            sys.executable,
            "python -m src.main",
            "--conf",
            config_arg,
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


def _start_fake_bot_with_equals(config_arg: str, cwd: Path) -> subprocess.Popen[bytes]:
    """Start a sleeping process that uses the --conf=VALUE argument form."""
    process = subprocess.Popen(  # noqa: S603 - fixed bash and Python executables
        [
            BASH_PATH,
            "-c",
            'exec -a "$1" "$2" -c "import time; time.sleep(30)" "$3" "$4"',
            "fake-bot",
            f"python -m src.main --conf={config_arg}",
            sys.executable,
            "python -m src.main",
            f"--conf={config_arg}",
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
    msg = "fake --conf= bot process did not exec"
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
stop_pid_file_instance "$(instance_pid_file "$1" "$2")" "$(resolve_config_path "$1" "$2")"
"""
    return _run_bash(script, str(project), config_file)


def _start_graceful_bot(config_arg: str, cwd: Path) -> subprocess.Popen[bytes]:
    """Start a process that records readiness, then exits cleanly on SIGTERM."""
    ready_marker = cwd / ".graceful-bot-ready"
    code = (
        "import signal, sys, time\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        f"open({str(ready_marker)!r}, 'w', encoding='utf-8').close()\n"
        "time.sleep(30)\n"
    )
    process = subprocess.Popen(  # noqa: S603 - fixed bash and Python executables
        [
            BASH_PATH,
            "-c",
            'exec -a "$1" "$2" -c "$3" "$4" "$5" "$6"',
            "fake-bot",
            f"python -m src.main --conf {config_arg}",
            sys.executable,
            code,
            "python -m src.main",
            "--conf",
            config_arg,
        ],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(5000):
        if "src.main" in _process_args(process.pid) and ready_marker.is_file():
            return process
        os.sched_yield()
    process.kill()
    process.wait(timeout=5)
    msg = "graceful fake bot process did not become ready"
    raise AssertionError(msg)


def _start_delayed_exit_bot(
    config_arg: str, cwd: Path, delay: float = 2.0
) -> subprocess.Popen[bytes]:
    """Start a bot-shaped process that exits only after a SIGTERM delay."""
    code = (
        "import signal, sys, time\n"
        "def stop(*_):\n"
        f"    time.sleep({delay!r})\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "while True: time.sleep(0.05)\n"
    )
    process = subprocess.Popen(  # noqa: S603 - fixed bash and Python executables
        [
            BASH_PATH,
            "-c",
            'exec -a "$1" "$2" -c "$3" "$4" "$5"',
            "fake-bot",
            f"python -m src.main --conf {config_arg}",
            sys.executable,
            code,
            "python -m src.main",
            "--conf",
            config_arg,
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
    msg = "delayed-exit fake bot process did not exec"
    raise AssertionError(msg)


def _write_stub_project(project: Path) -> Path:
    """Create a project directory whose venv Python records its launch."""
    project.mkdir(parents=True)
    (project / "bot.ini").write_text("", encoding="utf-8")
    bin_dir = project / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "python3"
    stub.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--version" ]]; then
    echo "Python 3.12.0"
    exit 0
fi
if [[ "${1:-}" == "-c" ]]; then
    if [[ "${2:-}" == *"[0]"* ]]; then
        echo 3
    else
        echo 12
    fi
    exit 0
fi
if [[ "${1:-}" == "-I" && "${2:-}" == "-B" ]]; then
    if [[ -n "${STUB_DEPENDENCY_LOG:-}" ]]; then
        printf '%s\\n' "$*" >> "${STUB_DEPENDENCY_LOG}"
    fi
    count_file="${STUB_DEPENDENCY_COUNT:-}"
    count=0
    if [[ -n "${count_file}" && -f "${count_file}" ]]; then
        count="$(cat "${count_file}")"
    fi
    count=$((count + 1))
    if [[ -n "${count_file}" ]]; then
        printf '%s\\n' "${count}" > "${count_file}"
    fi
    if [[ "${STUB_DEPENDENCY_CHECK:-pass}" == "fail" && "${count}" -ge 2 ]]; then
        echo "ERROR: Missing required packages: aiohttp" >&2
        echo "Please install dependencies with:" >&2
        echo "  pip install -r requirements.txt" >&2
        exit 1
    fi
    exit 0
fi
printf '%s\\n' "$@" > "${STUB_MARKER:?}"
exit 0
""",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _launcher_env(project: Path, marker: Path, **overrides: str) -> dict[str, str]:
    """Return an environment that uses the project stub, not host Python."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(project / "home"),
        "STUB_MARKER": str(marker),
        "DISCORDIANAI_STOP_TIMEOUT": "5",
        **overrides,
    }


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
        assert bot_pid_file.name.startswith(".bot-bot-")
        assert prod_pid_file.name.startswith(".bot-prod-")
        assert bot_pid_file.name.endswith(".pid")
        assert prod_pid_file.name.endswith(".pid")
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


def test_conf_equals_form_is_recognised(tmp_path):
    """--conf=VALUE must yield the same config argument as --conf VALUE."""
    project = tmp_path / "project"
    project.mkdir()
    config = project / "bot.ini"
    config.write_text("", encoding="utf-8")
    bot = _start_fake_bot_with_equals(str(config), project)
    try:
        script = """
set -euo pipefail
source "$LAUNCHER_LIB"
process_conf_argument "$1"
"""
        completed = _run_bash(script, str(bot.pid))

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == str(config)
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


def test_straggler_lookup_matches_the_conf_equals_form(tmp_path):
    """A bot started with --conf=VALUE must still be found by the straggler scan."""
    project = tmp_path / "project"
    project.mkdir()
    config = project / "bot.ini"
    config.write_text("", encoding="utf-8")
    bot = _start_fake_bot_with_equals(str(config), project)
    try:
        script = """
set -euo pipefail
source "$LAUNCHER_LIB"
straggler_pids "$1"
"""
        completed = _run_bash(script, str(config))

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.split() == [str(bot.pid)]
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


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


def test_same_basename_in_different_directories_gets_a_different_pid_file(tmp_path):
    """The hash in the name keeps two configs called bot.ini apart."""
    project = tmp_path / "project"
    for folder in ("one", "two"):
        (project / folder).mkdir(parents=True)
        (project / folder / "bot.ini").write_text("", encoding="utf-8")

    first = _instance_pid_file(project, "one/bot.ini")
    second = _instance_pid_file(project, "two/bot.ini")

    assert first != second
    assert first.name.startswith(".bot-bot-")
    assert second.name.startswith(".bot-bot-")


def test_straggler_lookup_matches_a_config_path_with_spaces(tmp_path):
    """A checkout path may contain a space; /proc keeps it as one argument."""
    project = tmp_path / "space project"
    project.mkdir()
    (project / "bot config.ini").write_text("", encoding="utf-8")
    bot = _start_fake_bot("bot config.ini", project)
    try:
        script = """
set -euo pipefail
source "$LAUNCHER_LIB"
straggler_pids "bot config.ini"
"""
        completed = _run_bash(script, cwd=project)

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.split() == [str(bot.pid)]
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


def test_stop_timeout_is_environment_overridable():
    """Tests and supervisors can shorten the force-kill wait without editing code."""
    script = """
set -euo pipefail
source "$LAUNCHER_LIB"
launcher_stop_timeout
"""
    completed = _run_bash(script, env={"DISCORDIANAI_STOP_TIMEOUT": "3"})

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "3"


def test_launcher_script_derives_its_pid_file_per_config(tmp_path):
    """The script itself must not fall back to one shared PID file."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    match = re.search(r"^PID_FILE=(.+)$", source, re.MULTILINE)
    assert match, "discordian.sh has no PID_FILE assignment"
    assignment = match.group(1)
    assert "instance_pid_file" in assignment

    project = tmp_path / "project"
    for folder in ("one", "two"):
        (project / folder).mkdir(parents=True)
        (project / folder / "bot.ini").write_text("", encoding="utf-8")

    script = f"""
set -euo pipefail
source "$LAUNCHER_LIB"
PROJECT_DIR="$1"
CONFIG_FILE="$2"
PID_FILE={assignment}
printf '%s\n' "$PID_FILE"
"""

    first = _run_bash(script, str(project), "one/bot.ini")
    second = _run_bash(script, str(project), "two/bot.ini")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout.strip() != second.stdout.strip()


def test_launcher_quotes_a_python_path_with_spaces_and_stops_the_legacy_instance(tmp_path):
    """A space in the checkout path must not turn the venv path into a command."""
    project = tmp_path / "space project"
    marker = tmp_path / "launch-args.txt"
    _write_stub_project(project)
    bot = _start_fake_bot("bot.ini", project)
    legacy = project / ".bot.pid"
    legacy.write_text(f"{bot.pid}\n", encoding="utf-8")
    try:
        script = f"""
set -euo pipefail
"{SCRIPT_PATH}" -c bot.ini -f "$1"
"""
        completed = _run_bash(
            script,
            str(project),
            env=_launcher_env(project, marker),
            cwd=tmp_path,
        )

        assert completed.returncode == 0, completed.stderr
        _assert_stopped(bot)
        assert not legacy.exists(), "the legacy PID file was not consumed"
        assert marker.is_file(), completed.stderr
        launched = marker.read_text(encoding="utf-8").splitlines()
        assert launched[:3] == ["-m", "src.main", "--conf"]
        assert launched[3] == str(project / "bot.ini")
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


def test_launcher_sigterm_stops_a_straggler_for_the_same_config(tmp_path):
    """Removing the straggler kill must leave the old process running."""
    project = tmp_path / "space project"
    marker = tmp_path / "launch-args.txt"
    _write_stub_project(project)
    bot = _start_fake_bot("bot.ini", project)
    try:
        script = f"""
set -euo pipefail
"{SCRIPT_PATH}" -c bot.ini -f "$1"
"""
        completed = _run_bash(
            script,
            str(project),
            env=_launcher_env(project, marker),
            cwd=tmp_path,
        )

        assert completed.returncode == 0, completed.stderr
        _assert_stopped(bot)
        assert marker.is_file(), completed.stderr
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


def test_stop_pid_file_instance_takes_the_graceful_branch(tmp_path):
    """A child that exits on SIGTERM is not force-killed."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "bot.ini").write_text("", encoding="utf-8")
    bot = _start_graceful_bot("bot.ini", project)
    pid_file = _instance_pid_file(project, "bot.ini")
    pid_file.write_text(f"{bot.pid}\n", encoding="utf-8")
    try:
        script = """
set -euo pipefail
source "$LAUNCHER_LIB"
log() { printf '%s\n' "$1" >&2; }
stop_pid_file_instance "$(instance_pid_file "$1" "$2")" "$(resolve_config_path "$1" "$2")"
"""
        completed = _run_bash(
            script,
            str(project),
            "bot.ini",
            env={"DISCORDIANAI_STOP_TIMEOUT": "5"},
        )

        assert completed.returncode == 0, completed.stderr
        assert "Stopping previous instance" in completed.stderr
        assert "Force-killing" not in completed.stderr
        _assert_stopped(bot)
        assert not pid_file.exists()
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


def test_stale_pid_file_for_an_unrelated_process_is_removed_without_a_signal(tmp_path):
    """A reboot can leave an unrelated PID in the file; it must keep running."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "bot.ini").write_text("", encoding="utf-8")
    unrelated = subprocess.Popen(["/bin/sleep", "30"])
    pid_file = _instance_pid_file(project, "bot.ini")
    pid_file.write_text(f"{unrelated.pid}\n", encoding="utf-8")
    try:
        completed = _stop_instance(project, "bot.ini")

        assert completed.returncode == 0, completed.stderr
        assert unrelated.poll() is None, "an unrelated process was signalled"
        assert not pid_file.exists()
    finally:
        if unrelated.poll() is None:
            unrelated.kill()
        unrelated.wait(timeout=5)


_SYSTEMD_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "s": " ",
}


def _expand_systemd_percent(value: str) -> str:
    """Decode ``%%`` and reject an unescaped systemd specifier."""
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "%":
            result.append(value[index])
            index += 1
            continue
        assert value[index + 1 : index + 2] == "%", f"unescaped specifier in {value!r}"
        result.append("%")
        index += 2
    return "".join(result)


def _expand_systemd_dollar(value: str) -> str:
    """Decode ``$$`` and reject an unescaped environment expansion."""
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "$":
            result.append(value[index])
            index += 1
            continue
        assert value[index + 1 : index + 2] == "$", f"unescaped dollar in {value!r}"
        result.append("$")
        index += 2
    return "".join(result)


def _split_systemd_words(value: str) -> list[str]:
    """Split a systemd word list with double quotes and C-style escapes."""
    words: list[str] = []
    current: list[str] = []
    quoted = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == '"':
            quoted = not quoted
            index += 1
            continue
        if character == "\\":
            escaped = value[index + 1 : index + 2]
            assert escaped in _SYSTEMD_ESCAPES, f"unknown systemd escape in {value!r}"
            current.append(_SYSTEMD_ESCAPES[escaped])
            index += 2
            continue
        if character.isspace() and not quoted:
            if current:
                expanded = _expand_systemd_percent("".join(current))
                words.append(_expand_systemd_dollar(expanded))
                current = []
            index += 1
            continue
        current.append(character)
        index += 1
    assert not quoted, f"unterminated quote in {value!r}"
    if current:
        expanded = _expand_systemd_percent("".join(current))
        words.append(_expand_systemd_dollar(expanded))
    return words


def _parse_systemd_unit(text: str) -> dict[str, list[str]]:
    """Return each directive's raw value, keeping repeated lines in order."""
    directives: dict[str, list[str]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "[")):
            continue
        key, separator, value = stripped.partition("=")
        assert separator, f"not a systemd directive: {line!r}"
        directives.setdefault(key, []).append(value)
    return directives


def _escaped_systemd_path(path: str) -> str:
    """Return a path value with every percent doubled for systemd."""
    return path.replace("%", "%%")


def _generate_systemd_unit(
    tmp_path: Path,
    project: Path,
    home: Path,
    *,
    config_arg: str = "bot.ini",
) -> tuple[Path, list[str]]:
    """Run the real launcher with a stub systemctl and return its unit and calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "systemctl-calls.txt"
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "${SYSTEMCTL_CALLS:?}"
if [[ "$1" == "--user" && "$2" == "is-active" ]]; then
    echo inactive
    exit 3
fi
exit 0
""",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    script = f"""
set -euo pipefail
"{SCRIPT_PATH}" --install-systemd "$2" -f "$1"
"""
    completed = _run_bash(
        script,
        str(project),
        config_arg,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(home),
            "SYSTEMCTL_CALLS": str(calls),
        },
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    instance = Path(config_arg).name.removesuffix(".ini")
    unit = home / ".config" / "systemd" / "user" / f"discordian-bot@{instance}.service"
    return unit, calls.read_text(encoding="utf-8").splitlines()


def _assert_unit_directives(text: str, project: Path, home: Path) -> None:
    """Assert the quoting rule for each directive and the decoded values."""
    directives = _parse_systemd_unit(text)

    exec_start = directives["ExecStart"][0]
    assert exec_start.startswith('"')
    assert _split_systemd_words(exec_start) == [
        str(SCRIPT_PATH),
        "-c",
        "bot.ini",
        "-f",
        str(project),
    ]

    working_directory = directives["WorkingDirectory"][0]
    assert not working_directory.startswith('"')
    assert working_directory == _escaped_systemd_path(str(project))

    log_path = _escaped_systemd_path(str(project / "bot.log"))
    assert directives["StandardOutput"] == [f"append:{log_path}"]
    assert directives["StandardError"] == [f"append:{log_path}"]

    read_write_paths = directives["ReadWritePaths"][0]
    assert read_write_paths.startswith('"')
    assert _split_systemd_words(read_write_paths) == [str(project)]

    environment: dict[str, str] = {}
    home_entry = ""
    for raw in directives["Environment"]:
        words = _split_systemd_words(raw)
        assert len(words) == 1, f"Environment is not one assignment: {raw!r}"
        name, separator, value = words[0].partition("=")
        assert separator, f"Environment has no assignment: {raw!r}"
        environment[name] = value
        if name == "HOME":
            home_entry = raw

    assert environment["HOME"] == str(home)
    assert environment["LANG"] == "en_US.UTF-8"
    assert environment["PATH"].endswith(
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    )
    if any(character.isspace() for character in str(home)):
        assert home_entry.startswith('"HOME=')
        assert home_entry.endswith('"')
    else:
        assert home_entry.startswith("HOME=")


def test_install_systemd_quotes_only_word_lists_and_starts_the_unit(tmp_path):
    """ExecStart and ReadWritePaths are quoted; the path directives are not."""
    project = tmp_path / "space project"
    home = tmp_path / "home"
    _write_stub_project(project)
    unit, invocations = _generate_systemd_unit(tmp_path, project, home)

    _assert_unit_directives(unit.read_text(encoding="utf-8"), project, home)
    assert invocations == [
        "--user daemon-reload",
        "--user enable discordian-bot@bot.service",
        "--user is-active --quiet discordian-bot@bot.service",
        "--user start discordian-bot@bot.service",
    ]


def test_install_systemd_escapes_percent_quotes_and_backslashes(tmp_path):
    """Each directive receives the escaping systemd applies to it."""
    project = tmp_path / 'space 50% "quote" \\backslash'
    home = tmp_path / "home 25%"
    _write_stub_project(project)
    unit, _invocations = _generate_systemd_unit(tmp_path, project, home)

    text = unit.read_text(encoding="utf-8")
    _assert_unit_directives(text, project, home)
    directives = _parse_systemd_unit(text)
    assert "%%" in directives["WorkingDirectory"][0]
    assert "\\\\" in directives["ExecStart"][0]
    assert '\\"' in directives["ExecStart"][0]
    assert '\\"' in directives["ReadWritePaths"][0]
    assert 'Environment="HOME=' in text


def test_install_systemd_unit_passes_the_systemd_validator_when_available(tmp_path):
    """The unit verifies with systemd, or the parser check alone must pass."""
    project = tmp_path / "space project 50%"
    home = tmp_path / "home"
    _write_stub_project(project)
    unit, _invocations = _generate_systemd_unit(tmp_path, project, home)

    text = unit.read_text(encoding="utf-8")
    _assert_unit_directives(text, project, home)

    analyzer = shutil.which("systemd-analyze")
    if analyzer is None:
        return
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    completed = subprocess.run(  # noqa: S603 - fixed systemd-analyze executable
        [analyzer, "verify", "--user", str(unit)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "XDG_RUNTIME_DIR": str(runtime),
        },
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "fatal error" not in output.lower(), output


def test_unknown_argument_exits_nonzero_without_stopping_the_running_instance(tmp_path):
    """A typo must not shift away and restart the default config's instance."""
    project = tmp_path / "project"
    marker = tmp_path / "launch-args.txt"
    _write_stub_project(project)
    bot = _start_fake_bot("bot.ini", project)
    try:
        script = f"""
set -euo pipefail
"{SCRIPT_PATH}" -c bot.ini -f "$1" --not-a-real-option
"""
        completed = _run_bash(
            script,
            str(project),
            env=_launcher_env(project, marker),
            cwd=tmp_path,
        )

        assert completed.returncode == 2, completed.stderr
        assert "not-a-real-option" in completed.stderr
        assert (
            bot.poll() is None
        ), "the launcher signalled the instance after rejecting an argument"
        assert not marker.exists(), "the launcher started the bot after rejecting an argument"
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


def test_equals_config_with_a_missing_file_exits_before_stopping(tmp_path):
    """--config=FILE must be parsed before the running instance is signalled."""
    project = tmp_path / "project"
    marker = tmp_path / "launch-args.txt"
    _write_stub_project(project)
    bot = _start_fake_bot("bot.ini", project)
    try:
        script = f"""
set -euo pipefail
"{SCRIPT_PATH}" --config=prod.ini -f "$1"
"""
        completed = _run_bash(
            script,
            str(project),
            env=_launcher_env(project, marker),
            cwd=tmp_path,
        )

        assert completed.returncode != 0, completed.stderr
        assert "prod.ini" in completed.stderr
        assert bot.poll() is None, "a missing config stopped the running bot.ini instance"
        assert not marker.exists()
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


def test_equals_config_selects_the_requested_file(tmp_path):
    """--config=FILE is accepted instead of being silently discarded."""
    project = tmp_path / "project"
    marker = tmp_path / "launch-args.txt"
    _write_stub_project(project)
    (project / "prod.ini").write_text("", encoding="utf-8")
    script = f"""
set -euo pipefail
"{SCRIPT_PATH}" --config=prod.ini -f "$1"
"""
    completed = _run_bash(
        script,
        str(project),
        env=_launcher_env(project, marker),
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    launched = marker.read_text(encoding="utf-8").splitlines()
    assert launched[:3] == ["-m", "src.main", "--conf"]
    assert launched[3] == str(project / "prod.ini")


def test_install_systemd_escapes_dollar_in_exec_start(tmp_path):
    """A dollar in the project path must survive systemd as a literal dollar."""
    project = tmp_path / "price$home"
    home = tmp_path / "home"
    _write_stub_project(project)
    unit, _invocations = _generate_systemd_unit(tmp_path, project, home)

    text = unit.read_text(encoding="utf-8")
    exec_start = _parse_systemd_unit(text)["ExecStart"][0]
    assert "price$$home" in exec_start, exec_start
    assert "price$home" not in exec_start, exec_start
    _assert_unit_directives(text, project, home)


def test_install_systemd_accepts_an_absolute_config_path(tmp_path):
    """The install path uses the same config resolver as the run path."""
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write_stub_project(project)
    config = project / "bot.ini"
    unit, _invocations = _generate_systemd_unit(
        tmp_path,
        project,
        home,
        config_arg=str(config),
    )

    assert unit.is_file()
    exec_start = _parse_systemd_unit(unit.read_text(encoding="utf-8"))["ExecStart"][0]
    words = _split_systemd_words(exec_start)
    assert words == [str(SCRIPT_PATH), "-c", str(config), "-f", str(project)]
    assert Path(words[2]).is_absolute()


def test_install_systemd_restarts_an_active_unit(tmp_path):
    """Re-installing a running unit must restart it instead of doing nothing."""
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write_stub_project(project)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "systemctl-calls.txt"
    active_marker = tmp_path / "unit-active"
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "${SYSTEMCTL_CALLS:?}"
if [[ "$1" == "--user" && "$2" == "is-active" ]]; then
    if [[ -f "${UNIT_ACTIVE_MARKER:?}" ]]; then
        echo active
        exit 0
    fi
    echo inactive
    exit 3
fi
exit 0
""",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    script = f"""
set -euo pipefail
"{SCRIPT_PATH}" --install-systemd bot.ini -f "$1"
"""
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(home),
        "SYSTEMCTL_CALLS": str(calls),
        "UNIT_ACTIVE_MARKER": str(active_marker),
    }

    first = _run_bash(script, str(project), env=env, cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    active_marker.write_text("", encoding="utf-8")
    second = _run_bash(script, str(project), env=env, cwd=tmp_path)
    assert second.returncode == 0, second.stderr

    invocations = calls.read_text(encoding="utf-8").splitlines()
    assert "--user start discordian-bot@bot.service" in invocations
    assert invocations[-2:] == [
        "--user is-active --quiet discordian-bot@bot.service",
        "--user restart discordian-bot@bot.service",
    ]


def test_launcher_waits_for_a_straggler_to_exit_before_starting(tmp_path):
    """A straggler gets the same bounded wait as the PID-file path."""
    project = tmp_path / "project"
    marker = tmp_path / "launch-args.txt"
    _write_stub_project(project)
    bot = _start_delayed_exit_bot("bot.ini", project, delay=2.0)
    try:
        script = f"""
set -euo pipefail
"{SCRIPT_PATH}" -c bot.ini -f "$1"
"""
        completed = _run_bash(
            script,
            str(project),
            env=_launcher_env(project, marker),
            cwd=tmp_path,
        )

        assert completed.returncode == 0, completed.stderr
        assert bot.poll() is not None, "a new instance started before the straggler exited"
        assert marker.is_file(), completed.stderr
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


def test_missing_dependencies_exit_before_stopping_the_instance(tmp_path):
    """A pull that adds a dependency must not stop the healthy old bot."""
    project = tmp_path / "project"
    marker = tmp_path / "launch-args.txt"
    count = tmp_path / "dependency-count.txt"
    _write_stub_project(project)
    bot = _start_fake_bot("bot.ini", project)
    try:
        script = f"""
set -euo pipefail
"{SCRIPT_PATH}" -c bot.ini -f "$1"
"""
        completed = _run_bash(
            script,
            str(project),
            env=_launcher_env(
                project,
                marker,
                STUB_DEPENDENCY_CHECK="fail",
                STUB_DEPENDENCY_COUNT=str(count),
            ),
            cwd=tmp_path,
        )

        assert completed.returncode != 0, completed.stderr
        assert "Missing required packages: aiohttp" in completed.stderr
        assert bot.poll() is None, "the launcher stopped the instance before its dependency check"
        assert not marker.exists(), "the launcher started after a failed dependency check"
    finally:
        if bot.poll() is None:
            bot.kill()
            bot.wait(timeout=5)


def test_dependency_check_runs_isolated_before_launch(tmp_path):
    """The check runs the project's own script with local imports disabled."""
    project = tmp_path / "project"
    marker = tmp_path / "launch-args.txt"
    check_log = tmp_path / "dependency-check.log"
    _write_stub_project(project)
    script = f"""
set -euo pipefail
"{SCRIPT_PATH}" -c bot.ini -f "$1"
"""
    completed = _run_bash(
        script,
        str(project),
        env=_launcher_env(project, marker, STUB_DEPENDENCY_LOG=str(check_log)),
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.is_file(), completed.stderr
    invoked = check_log.read_text(encoding="utf-8").splitlines()
    assert f"-I -B {project}/src/dependency_check.py" in invoked


def test_resolve_python_prefers_the_project_venv_over_pyenv(tmp_path):
    """The checkout's own venv wins when its dependencies are available."""
    project = tmp_path / "project"
    marker = tmp_path / "launch-args.txt"
    _write_stub_project(project)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pyenv_python = tmp_path / "pyenv-python"
    pyenv_python.write_text(
        """#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then
    echo "Python 3.12.0"
    exit 0
fi
if [[ "${1:-}" == "-c" ]]; then
    if [[ "${2:-}" == *"[0]"* ]]; then
        echo 3
    else
        echo 12
    fi
    exit 0
fi
printf 'pyenv %s\n' "$@" >> "${STUB_MARKER:?}"
exit 0
""",
        encoding="utf-8",
    )
    pyenv_python.chmod(0o755)
    pyenv = bin_dir / "pyenv"
    pyenv.write_text(
        f"""#!/usr/bin/env bash
if [[ "$1" == "which" ]]; then
    echo "{pyenv_python}"
    exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    pyenv.chmod(0o755)
    script = f"""
set -euo pipefail
"{SCRIPT_PATH}" -c bot.ini -f "$1"
"""
    completed = _run_bash(
        script,
        str(project),
        env=_launcher_env(project, marker, PATH=f"{bin_dir}:/usr/bin:/bin"),
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    launched = marker.read_text(encoding="utf-8").splitlines()
    assert launched[:3] == ["-m", "src.main", "--conf"]
    assert launched[3] == str(project / "bot.ini")
