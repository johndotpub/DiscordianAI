"""Rate-limit clock and maintenance regression tests.

The limiter must use a monotonic clock for its windows, and stale-entry sweeps
must stay off the request path.
"""

from unittest.mock import Mock, patch

import pytest

from src.rate_limits import RateLimiter, check_rate_limit


class Clock:
    """A controllable wall clock and monotonic clock pair."""

    def __init__(self, monotonic: float = 0.0, wall: float = 1_700_000_000.0):
        self.monotonic = monotonic
        self.wall = wall


def install_clock(monkeypatch, clock: Clock) -> None:
    """Make the rate limiter read from the supplied clock."""
    monkeypatch.setattr("src.rate_limits.time.monotonic", lambda: clock.monotonic)
    monkeypatch.setattr("src.rate_limits.time.time", lambda: clock.wall)


def test_backward_wall_clock_step_does_not_extend_active_window(monkeypatch):
    """A backward NTP step must not keep a user limited after the window ends."""
    clock = Clock(monotonic=100.0)
    install_clock(monkeypatch, clock)
    limiter = RateLimiter()
    logger = Mock()

    assert limiter.check_rate_limit(1, 2, 10, logger) is True
    assert limiter.check_rate_limit(1, 2, 10, logger) is True

    # Wall clock steps back an hour while monotonic time moves past the window.
    clock.wall -= 3600
    clock.monotonic += 10.5

    assert limiter.check_rate_limit(1, 2, 10, logger) is True


def test_forward_wall_clock_step_does_not_allow_a_burst(monkeypatch):
    """A forward NTP step must not reset the active window early."""
    clock = Clock(monotonic=100.0)
    install_clock(monkeypatch, clock)
    limiter = RateLimiter()
    logger = Mock()

    assert limiter.check_rate_limit(1, 2, 60, logger) is True
    assert limiter.check_rate_limit(1, 2, 60, logger) is True

    # Wall clock jumps forward an hour; monotonic time has barely moved.
    clock.wall += 3600
    clock.monotonic += 1.0

    assert limiter.check_rate_limit(1, 2, 60, logger) is False


def test_window_arithmetic_and_retry_time_are_unchanged(monkeypatch):
    """Ten requests per 60 seconds admits ten, then waits for the window."""
    clock = Clock(monotonic=0.0)
    install_clock(monkeypatch, clock)
    limiter = RateLimiter()
    logger = Mock()

    for _ in range(10):
        assert limiter.check_rate_limit(1, 10, 60, logger) is True

    clock.monotonic = 59.0
    assert limiter.check_rate_limit(1, 10, 60, logger) is False

    clock.monotonic = 61.0
    assert limiter.check_rate_limit(1, 10, 60, logger) is True

    clock.monotonic = 76.0
    assert limiter.check_rate_limit(1, 10, 60, logger) is True
    assert limiter.last_command_count[1] == 2

    clock.monotonic = 121.1
    assert limiter.check_rate_limit(1, 10, 60, logger) is True
    assert limiter.last_command_count[1] == 1


def test_requests_never_sweep_but_maintenance_does(monkeypatch):
    """Checking requests must not trigger a full stale-entry scan."""
    clock = Clock(monotonic=0.0)
    install_clock(monkeypatch, clock)
    limiter = RateLimiter()
    logger = Mock()

    with patch.object(
        limiter,
        "cleanup_stale_entries",
        wraps=limiter.cleanup_stale_entries,
    ) as sweep:
        for user_id in range(250):
            limiter.check_rate_limit(user_id % 4, 10, 60, logger)

        assert sweep.call_count == 0

        limiter.last_command_timestamps[999] = -1000.0
        limiter.last_command_count[999] = 1
        clock.monotonic = 1000.0

        limiter.run_maintenance(60)

        assert sweep.call_count == 1
        assert 999 not in limiter.last_command_timestamps
        assert 999 not in limiter.last_command_count


@pytest.mark.asyncio
async def test_per_user_isolation_and_fail_open_cooldown_unchanged(monkeypatch):
    """Users stay isolated, and repeated failures still end in a cooldown."""
    clock = Clock(monotonic=100.0)
    install_clock(monkeypatch, clock)
    logger = Mock()

    limiter = RateLimiter()
    assert limiter.check_rate_limit(1, 2, 60, logger) is True
    assert limiter.check_rate_limit(1, 2, 60, logger) is True
    assert limiter.check_rate_limit(1, 2, 60, logger) is False
    assert limiter.check_rate_limit(2, 2, 60, logger) is True

    failing_limiter = RateLimiter()
    failing_limiter.check_rate_limit = Mock(side_effect=ValueError("boom"))
    user = Mock()
    user.id = 1
    user.name = "TestUser"

    # The first two errors fail open, the third enters cooldown.
    assert await check_rate_limit(user, failing_limiter, 10, 60, logger) is True
    assert await check_rate_limit(user, failing_limiter, 10, 60, logger) is True
    assert await check_rate_limit(user, failing_limiter, 10, 60, logger) is False
    assert await check_rate_limit(user, failing_limiter, 10, 60, logger) is False

    # Cooldown is a duration, not a wall-clock deadline.
    clock.wall -= 3600
    clock.monotonic += 61.0
    assert await check_rate_limit(user, failing_limiter, 10, 60, logger) is True
