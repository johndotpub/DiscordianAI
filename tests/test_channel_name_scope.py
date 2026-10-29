"""Scope tests for resolving ALLOWED_CHANNELS names across guilds."""

import logging
from types import SimpleNamespace

from src import message_router

LOGGER_NAME = "channel-name-scope-test"


class DummyChannel:
    def __init__(self, channel_id: int, name: str):
        self.id = channel_id
        self.name = name


class DummyGuild:
    def __init__(self, guild_id: int, name: str, channels: list[tuple[int, str]]):
        self.id = guild_id
        self.name = name
        self.text_channels = [
            DummyChannel(channel_id, channel) for channel_id, channel in channels
        ]
        self.forums = []
        self.channels = self.text_channels


def _deps(
    names: list[str],
    *,
    guilds: list[str] | None = None,
    guild_ids: list[int] | None = None,
) -> dict:
    deps = {
        "ALLOWED_CHANNELS": names,
        "logger": logging.getLogger(LOGGER_NAME),
    }
    if guilds is not None:
        deps["ALLOWED_GUILDS"] = guilds
    if guild_ids is not None:
        deps["ALLOWED_GUILD_IDS"] = guild_ids
    return deps


def _bot(*guilds: DummyGuild) -> SimpleNamespace:
    return SimpleNamespace(guilds=list(guilds))


def test_name_in_second_guild_is_resolved_when_guilds_are_unscoped():
    first = DummyGuild(1, "First", [(10, "general")])
    second = DummyGuild(2, "Second", [(20, "ai-art")])
    deps = _deps(["ai-art"])

    resolved = message_router.resolve_allowed_channel_names(
        _bot(first, second), deps, deps["logger"]
    )

    assert resolved == {20}


def test_allowed_guilds_narrows_names_to_the_named_guild():
    first = DummyGuild(1, "First", [(10, "general")])
    second = DummyGuild(2, "Second", [(20, "ai-art")])
    deps = _deps(["ai-art"], guilds=["First"])

    resolved = message_router.resolve_allowed_channel_names(
        _bot(first, second), deps, deps["logger"]
    )

    assert resolved == set()


def test_allowed_guild_ids_searches_only_the_named_guild():
    first = DummyGuild(1, "First", [(10, "shared")])
    second = DummyGuild(2, "Second", [(20, "shared")])
    deps = _deps(["shared"], guild_ids=[2])

    resolved = message_router.resolve_allowed_channel_names(
        _bot(first, second), deps, deps["logger"]
    )

    assert resolved == {20}


def test_unscoped_boot_log_names_the_number_of_guilds_searched(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    first = DummyGuild(1, "First", [(10, "general")])
    second = DummyGuild(2, "Second", [(20, "ai-art")])
    deps = _deps(["general", "ai-art"])

    message_router.resolve_allowed_channel_names(_bot(first, second), deps, deps["logger"])

    lines = [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]
    assert any("all 2 guilds" in line for line in lines), lines
    assert not [
        record for record in caplog.records if record.levelno >= logging.WARNING
    ], "unscoped name matching is normal and must not warn"


def test_same_name_resolves_in_both_guilds_unscoped_and_one_guild_when_scoped():
    first = DummyGuild(1, "First", [(10, "general")])
    second = DummyGuild(2, "Second", [(20, "general")])
    bot = _bot(first, second)
    deps = _deps(["general"])

    assert message_router.resolve_allowed_channel_names(bot, deps, deps["logger"]) == {10, 20}

    deps["ALLOWED_GUILDS"] = ["First"]
    assert message_router.resolve_allowed_channel_names(bot, deps, deps["logger"]) == {10}
