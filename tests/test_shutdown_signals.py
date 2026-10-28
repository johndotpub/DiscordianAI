import asyncio
import os
from pathlib import Path
import signal
import sys
import textwrap
import time

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _environment():
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT) if not existing else f"{PROJECT_ROOT}{os.pathsep}{existing}"
    )
    return env


def _write_script(tmp_path, body):
    script = tmp_path / "shutdown_script.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


async def _start_script(script, *args):
    return await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        *map(str, args),
        cwd=PROJECT_ROOT,
        env=_environment(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _wait_for_path(path, proc, limit=10.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit
    while loop.time() < deadline:
        if path.exists():
            return
        if proc.returncode is not None:
            stdout, stderr = await proc.communicate()
            pytest.fail(
                f"process exited before becoming ready ({proc.returncode})\n"
                f"stdout:\n{stdout.decode()}\nstderr:\n{stderr.decode()}"
            )
        await asyncio.sleep(0.01)
    proc.kill()
    stdout, stderr = await proc.communicate()
    pytest.fail(
        f"timed out waiting for process readiness\n"
        f"stdout:\n{stdout.decode()}\nstderr:\n{stderr.decode()}"
    )


async def _wait_for_exit(proc, limit=10.0):
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=limit)
    except TimeoutError:
        proc.kill()
        stdout, stderr = await proc.communicate()
        pytest.fail(
            f"process did not exit within {limit}s\n"
            f"stdout:\n{stdout.decode()}\nstderr:\n{stderr.decode()}"
        )
    return stdout.decode(), stderr.decode()


async def _stop_process(proc):
    if proc.returncode is None:
        proc.kill()
        await proc.communicate()


SIGNAL_SCRIPT = """
import asyncio
import logging
import sys
from pathlib import Path

import discord

from src.bot_manager import DiscordBotManager

marker = Path(sys.argv[1])
shutdown_delay = float(sys.argv[2])
ready = marker.with_name(marker.name + ".ready")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("shutdown-signal-test")

bot = discord.Client(intents=discord.Intents.default())
manager = DiscordBotManager({"bot": bot, "logger": logger, "config": {}})


async def main():
    stop_event = asyncio.Event()

    async def fake_shutdown():
        with marker.open("a", encoding="utf-8") as handle:
            handle.write("shutdown\\n")
        print("SHUTDOWN_STARTED", flush=True)
        await asyncio.sleep(shutdown_delay)
        stop_event.set()

    manager.graceful_shutdown = fake_shutdown
    manager.register_events()
    await bot.setup_hook()
    manager.setup_signal_handlers()
    ready.write_text("ready", encoding="utf-8")

    try:
        await asyncio.wait_for(stop_event.wait(), timeout=5.0)
    except TimeoutError:
        print("HARNESS_TIMEOUT", file=sys.stderr, flush=True)
        return 3
    return 0


raise SystemExit(asyncio.run(main()))
"""

BOUNDED_SCRIPT = """
import asyncio
import logging
import sys
from pathlib import Path

import discord

from src.bot_manager import DiscordBotManager

ready = Path(sys.argv[1])

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
logger = logging.getLogger("bounded-shutdown-test")

bot = discord.Client(intents=discord.Intents.default())


async def slow_close():
    print("CLOSE_STARTED", flush=True)
    await asyncio.sleep(60)


bot.close = slow_close

manager = DiscordBotManager({"bot": bot, "logger": logger, "config": {}})
manager.SHUTDOWN_TIMEOUT = 0.5


async def main():
    manager.register_events()
    await bot.setup_hook()
    manager.setup_signal_handlers()
    ready.write_text("ready", encoding="utf-8")
    await asyncio.Event().wait()


raise SystemExit(asyncio.run(main()))
"""


@pytest.mark.asyncio
async def test_sigterm_runs_shutdown_once(tmp_path):
    marker = tmp_path / "shutdown.marker"
    script = _write_script(tmp_path, SIGNAL_SCRIPT)
    proc = await _start_script(script, marker, 0)

    try:
        await _wait_for_path(marker.with_name(marker.name + ".ready"), proc)
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = await _wait_for_exit(proc)
    finally:
        await _stop_process(proc)

    assert proc.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"
    assert marker.read_text(encoding="utf-8").splitlines() == ["shutdown"]
    assert stdout.count("SHUTDOWN_STARTED") == 1


@pytest.mark.asyncio
async def test_double_sigterm_runs_shutdown_once(tmp_path):
    marker = tmp_path / "shutdown.marker"
    script = _write_script(tmp_path, SIGNAL_SCRIPT)
    proc = await _start_script(script, marker, 1.0)

    try:
        await _wait_for_path(marker.with_name(marker.name + ".ready"), proc)
        proc.send_signal(signal.SIGTERM)
        await _wait_for_path(marker, proc)
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = await _wait_for_exit(proc)
    finally:
        await _stop_process(proc)

    assert proc.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"
    assert marker.read_text(encoding="utf-8").splitlines() == ["shutdown"]
    assert stdout.count("SHUTDOWN_STARTED") == 1


@pytest.mark.asyncio
async def test_shutdown_is_bounded_when_close_hangs(tmp_path):
    ready = tmp_path / "ready.marker"
    script = _write_script(tmp_path, BOUNDED_SCRIPT)
    proc = await _start_script(script, ready)

    try:
        await _wait_for_path(ready, proc)
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = await _wait_for_exit(proc, limit=10.0)
        elapsed = time.monotonic() - started
    finally:
        await _stop_process(proc)

    output = f"{stdout}\n{stderr}"
    assert proc.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"
    assert elapsed < 5.0, f"shutdown took {elapsed:.2f}s\n{output}"
    assert "timed out" in output.lower(), output
