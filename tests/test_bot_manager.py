import asyncio
import logging
import signal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from src.bot_manager import DiscordBotManager


class DummyBot:
    def __init__(self):
        self.event_handlers = {}
        self.user = SimpleNamespace(name="bot", id=1)
        self.guilds = [SimpleNamespace(id=10), SimpleNamespace(id=11)]
        self.presence_calls: list[tuple] = []
        self.closed_calls = 0

    def event(self, func):
        self.event_handlers[func.__name__] = func
        return func

    async def change_presence(self, activity=None, status=None):
        self.presence_calls.append((activity, status))

    def is_closed(self):
        return self.closed_calls > 0

    async def close(self):
        self.closed_calls += 1


class DummyTask(asyncio.Future):
    def __init__(self):
        super().__init__()

    def cancel(self):
        super().cancel()


class DummyHealthMonitor:
    async def run_all_health_checks(self, _clients, _deps):
        return None


@pytest.fixture
def base_deps(monkeypatch):
    logger = logging.getLogger("bot-manager-test")
    logger.addHandler(logging.NullHandler())

    bot = DummyBot()
    deps = {
        "bot": bot,
        "logger": logger,
        "config": {},
        "ACTIVITY_TYPE": "playing",
        "ACTIVITY_STATUS": "tests",
        "BOT_PRESENCE": "online",
        "DISCORD_TOKEN": "token",
    }

    monkeypatch.setattr("src.bot_manager.set_activity_status", lambda a, s: (a, s))
    monkeypatch.setattr("src.bot_manager.APIHealthMonitor", DummyHealthMonitor)

    return deps


@pytest.mark.asyncio
async def test_on_ready_sets_presence_and_health(monkeypatch, base_deps):
    tasks = []

    real_create_task = asyncio.create_task

    def fake_create_task(coro):
        task = real_create_task(coro)
        tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    manager = DiscordBotManager(base_deps)
    manager.register_events()

    on_ready = manager.bot.event_handlers["on_ready"]
    await on_ready()

    if tasks:
        await asyncio.gather(*tasks)

    assert manager.bot.presence_calls == [(("playing", "tests"), discord.Status.online)]
    assert base_deps["_health_task"] is tasks[0]


@pytest.mark.asyncio
async def test_on_message_routes_to_router(monkeypatch, base_deps):
    router_mock = AsyncMock()
    monkeypatch.setattr("src.bot_manager.handle_incoming_message", router_mock)

    manager = DiscordBotManager(base_deps)
    manager.register_events()

    message = SimpleNamespace(
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=99),
        mentions=[],
        guild=None,
    )

    on_message = manager.bot.event_handlers["on_message"]
    await on_message(message)

    router_mock.assert_awaited_once_with(message, base_deps, manager.bot)


@pytest.mark.asyncio
async def test_graceful_shutdown_closes_resources(base_deps):
    pool_manager = SimpleNamespace(close_all=AsyncMock())
    base_deps["connection_pool_manager"] = pool_manager

    health_task = DummyTask()
    base_deps["_health_task"] = health_task

    manager = DiscordBotManager(base_deps)

    await manager.graceful_shutdown()

    assert manager.bot.closed_calls == 1
    pool_manager.close_all.assert_awaited_once()
    assert health_task.cancelled()


@pytest.mark.asyncio
async def test_disconnect_and_resume_handlers(base_deps):
    manager = DiscordBotManager(base_deps)
    manager.register_events()

    await manager.bot.event_handlers["on_disconnect"]()
    await manager.bot.event_handlers["on_resumed"]()

    # No exceptions means handlers executed successfully


def test_setup_signal_handlers(monkeypatch, base_deps):
    calls = []

    def fake_signal(sig, handler):
        calls.append((sig, handler))

    monkeypatch.setattr("signal.signal", fake_signal)

    manager = DiscordBotManager(base_deps)
    manager.setup_signal_handlers()

    assert {sig for sig, _ in calls} == {signal.SIGTERM, signal.SIGINT}


def test_run_handles_keyboard_interrupt(monkeypatch, base_deps):
    class FakeLoop:
        def __init__(self):
            self.closed = False

        def run_until_complete(self, coro):
            return asyncio.run(coro)

        def close(self):
            self.closed = True

    manager = DiscordBotManager(base_deps)
    manager.graceful_shutdown = AsyncMock()
    manager.register_events = lambda: None

    base_deps["bot"].run = lambda _token=None: (_ for _ in ()).throw(KeyboardInterrupt)

    monkeypatch.setattr(asyncio, "new_event_loop", FakeLoop)
    monkeypatch.setattr(asyncio, "set_event_loop", lambda _loop=None: None)

    manager.run()

    manager.graceful_shutdown.assert_awaited_once()


def test_run_happy_path(base_deps):
    manager = DiscordBotManager(base_deps)
    ran = {}

    def mark_registered():
        ran.setdefault("registered", True)

    def mark_signals():
        ran.setdefault("signals", True)

    def run_bot(token):
        ran.setdefault("token", token)

    manager.register_events = mark_registered
    manager.setup_signal_handlers = mark_signals
    base_deps["bot"].run = run_bot

    manager.run()

    assert ran == {"registered": True, "signals": True, "token": "token"}
