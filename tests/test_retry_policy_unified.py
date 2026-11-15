"""Regression tests for the single shared retry policy."""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest

from src.error_handling import retry_after_seconds, safe_discord_send

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _function_definitions(name: str) -> list[Path]:
    definitions = []
    for path in SRC.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        definitions.extend(
            path
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        )
    return definitions


def test_retry_policy_is_defined_once():
    assert len(_function_definitions("is_retryable_status")) == 1
    assert len(_function_definitions("retry_after_seconds")) == 1


def test_retry_after_seconds_parses_and_bounds_values():
    assert retry_after_seconds({"Retry-After": "5"}) == 5
    assert retry_after_seconds({"retry-after": "60"}) == 30
    assert retry_after_seconds({}) is None


def _discord_response(status: int, headers: dict[str, str] | None = None) -> Mock:
    response = Mock()
    response.status = status
    response.reason = "response"
    response.headers = headers or {}
    return response


@pytest.mark.asyncio
async def test_discord_429_waits_the_requested_retry_after():
    channel = Mock()
    channel.send = AsyncMock(
        side_effect=discord.HTTPException(
            _discord_response(429, {"Retry-After": "5"}), "rate limited"
        )
    )
    sleep = AsyncMock()

    with patch("src.error_handling.asyncio.sleep", sleep):
        result = await safe_discord_send(channel, "hello", Mock(), max_retries=2)

    assert result is False
    assert channel.send.await_count == 2
    assert [call.args[0] for call in sleep.await_args_list] == [5.0]


@pytest.mark.asyncio
async def test_discord_rate_limited_uses_the_supplied_retry_after():
    channel = Mock()
    channel.send = AsyncMock(side_effect=discord.RateLimited(5))
    sleep = AsyncMock()

    with patch("src.error_handling.asyncio.sleep", sleep):
        result = await safe_discord_send(channel, "hello", Mock(), max_retries=2)

    assert result is False
    assert channel.send.await_count == 2
    assert [call.args[0] for call in sleep.await_args_list] == [5.0]


@pytest.mark.asyncio
async def test_discord_403_makes_one_attempt_without_sleeping():
    channel = Mock()
    channel.send = AsyncMock(
        side_effect=discord.Forbidden(_discord_response(403), "missing permissions")
    )
    sleep = AsyncMock()

    with patch("src.error_handling.asyncio.sleep", sleep):
        result = await safe_discord_send(channel, "hello", Mock())

    assert result is False
    assert channel.send.await_count == 1
    assert not sleep.called
