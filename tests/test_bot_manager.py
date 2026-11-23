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
        self.run_calls: list[tuple] = []

    def event(self, func):
        self.event_handlers[func.__name__] = func
        return func

    async def change_presence(self, activity=None, status=None):
        self.presence_calls.append((activity, status))

    def is_closed(self):
        return self.closed_calls > 0

    async def close(self):
        self.closed_calls += 1

    def run(self, token, **kwargs):
        self.run_calls.append((token, kwargs))


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
async def test_graceful_shutdown_closes_the_router_client(base_deps):
    router = SimpleNamespace(aclose=AsyncMock())
    base_deps["router"] = router
    manager = DiscordBotManager(base_deps)

    await manager.graceful_shutdown()

    router.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_and_resume_handlers(base_deps, caplog):
    manager = DiscordBotManager(base_deps)
    manager.register_events()

    with caplog.at_level(logging.WARNING, logger="bot-manager-test"):
        await manager.bot.event_handlers["on_disconnect"]()
    assert any("disconnected" in record.message.lower() for record in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="bot-manager-test"):
        await manager.bot.event_handlers["on_resumed"]()
    assert any("resumed" in record.message.lower() for record in caplog.records)


def test_setup_signal_handlers(monkeypatch, base_deps):
    calls = []

    def fake_signal(sig, handler):
        calls.append((sig, handler))

    monkeypatch.setattr("signal.signal", fake_signal)

    manager = DiscordBotManager(base_deps)
    manager.setup_signal_handlers()

    assert {sig for sig, _ in calls} == {signal.SIGTERM, signal.SIGINT}


@pytest.mark.asyncio
async def test_signal_handler_with_real_client_schedules_one_shutdown(monkeypatch, base_deps):
    captured_handlers = []

    def fake_signal(_sig, handler):
        captured_handlers.append(handler)

    monkeypatch.setattr("signal.signal", fake_signal)

    base_deps["bot"] = discord.Client(intents=discord.Intents.default())
    manager = DiscordBotManager(base_deps)
    manager.graceful_shutdown = AsyncMock()
    manager.register_events()
    await manager.bot.setup_hook()
    manager.setup_signal_handlers()

    assert len(captured_handlers) == 2

    captured_handlers[0](signal.SIGTERM, None)

    await asyncio.sleep(0)
    manager.graceful_shutdown.assert_awaited_once()


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

    base_deps["bot"].run = lambda _token=None, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt)

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

    def run_bot(token, **_kwargs):
        ran.setdefault("token", token)

    manager.register_events = mark_registered
    manager.setup_signal_handlers = mark_signals
    base_deps["bot"].run = run_bot

    manager.run()

    assert ran == {"registered": True, "signals": True, "token": "token"}


def test_run_disables_discord_default_logging(base_deps):
    manager = DiscordBotManager(base_deps)
    manager.register_events = lambda: None
    manager.setup_signal_handlers = lambda: None

    manager.run()

    assert base_deps["bot"].run_calls == [("token", {"log_handler": None})]


@pytest.mark.asyncio
async def test_graceful_shutdown_closes_discord_before_provider_pools(base_deps):
    """Discord stays available while provider pools drain."""
    order = []

    class OrderedBot(DummyBot):
        async def close(self):
            order.append("discord")
            await super().close()

    base_deps["bot"] = OrderedBot()
    pool_manager = SimpleNamespace(close_all=AsyncMock(side_effect=lambda: order.append("pools")))
    base_deps["connection_pool_manager"] = pool_manager

    manager = DiscordBotManager(base_deps)
    await manager.graceful_shutdown()

    assert order == ["discord", "pools"]


@pytest.mark.asyncio
async def test_shutdown_guard_logs_unexpected_error_and_exits_zero(monkeypatch, base_deps):
    """Any shutdown exception is contained and the process exits cleanly."""
    manager = DiscordBotManager(base_deps)

    async def failing_shutdown():
        msg = "shutdown backend failed"
        raise RuntimeError(msg)

    manager.graceful_shutdown = failing_shutdown
    exits = []
    monkeypatch.setattr("src.bot_manager.os._exit", exits.append)

    caught = None
    try:
        await manager._shutdown_with_timeout()
    except Exception as exc:  # noqa: BLE001 - the guard must contain everything
        caught = exc

    assert caught is None, f"shutdown guard let {caught!r} escape"
    assert exits == [0]


@pytest.mark.asyncio
async def test_disconnect_and_resume_publish_the_gateway_state(base_deps):
    """Health reads a real disconnect instead of discord.py's sticky readiness."""
    manager = DiscordBotManager(base_deps)
    manager.register_events()

    await manager.bot.event_handlers["on_disconnect"]()
    assert getattr(manager.bot, "discordian_gateway_connected", None) is False

    await manager.bot.event_handlers["on_resumed"]()
    assert getattr(manager.bot, "discordian_gateway_connected", None) is True
