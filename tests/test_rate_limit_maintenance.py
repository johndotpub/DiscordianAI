"""Maintenance and corrupted-state coverage for the rate limiter."""

from unittest.mock import Mock

from src.rate_limits import RateLimiter


class _Clock:
    """A controllable monotonic clock."""

    def __init__(self, monotonic: float = 0.0) -> None:
        self.monotonic = monotonic


def _install_clock(monkeypatch, clock: _Clock) -> None:
    """Make the limiter read from the supplied monotonic clock."""
    monkeypatch.setattr("src.rate_limits.time.monotonic", lambda: clock.monotonic)


def test_maintenance_without_an_observed_window_leaves_entries_alone():
    """A sweep before any request cannot guess which entries are stale."""
    limiter = RateLimiter()
    limiter.last_command_timestamps[1] = 0.0
    limiter.last_command_count[1] = 1

    limiter.run_maintenance(now=10_000.0)

    assert limiter.last_command_timestamps == {1: 0.0}
    assert limiter.last_command_count == {1: 1}


def test_maintenance_removes_expired_entries_and_keeps_active_ones(monkeypatch):
    """Only entries older than two windows are pruned, with the clock controlled."""
    clock = _Clock(monotonic=100.0)
    _install_clock(monkeypatch, clock)
    limiter = RateLimiter()
    logger = Mock()

    assert limiter.check_rate_limit(1, 5, 60, logger) is True
    clock.monotonic = 1000.0
    assert limiter.check_rate_limit(2, 5, 60, logger) is True
    clock.monotonic = 1100.0

    limiter.run_maintenance()

    assert 1 not in limiter.last_command_timestamps
    assert 1 not in limiter.last_command_count
    assert limiter.last_command_timestamps[2] == 1000.0
    assert limiter.last_command_count[2] == 1


def test_fail_open_recovers_from_non_numeric_internal_state():
    """Corrupted counters are repaired to zero instead of crashing or limiting."""
    limiter = RateLimiter()
    limiter._fail_open_errors = "three"
    limiter._fail_open_cooldown_until = "later"

    errors, cooldown_active, entering_cooldown = limiter.record_fail_open_error(now=100.0)

    assert errors == 1
    assert cooldown_active is False
    assert entering_cooldown is False
    assert limiter.fail_open_errors == 1
