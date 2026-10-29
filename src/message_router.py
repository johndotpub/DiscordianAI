"""Registry for Discord bot events."""

from typing import Any

import discord

from .conversation_manager import conversation_key_for_message
from .logging_adapter import get_logger_with_context
from .message_processor import process_channel_message, process_dm_message


def _normalise_name(value: Any) -> str:
    """Normalise a channel, guild, or configured name for comparison."""
    return str(value).strip().lstrip("#").strip().casefold()


def _as_int_set(values: Any) -> set[int]:
    """Convert a configured ID collection to a set of integers."""
    result: set[int] = set()
    for value in values or []:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _configured_channel_names(deps: dict[str, Any] | Any) -> set[str]:
    """Return normalised configured channel names."""
    return {
        _normalise_name(name)
        for name in (deps.get("ALLOWED_CHANNELS", []) or [])
        if str(name).strip()
    }


def _guild_filters(deps: dict[str, Any] | Any) -> tuple[set[int], set[str]]:
    """Return configured guild IDs and normalised guild names."""
    guild_ids = _as_int_set(deps.get("ALLOWED_GUILD_IDS", []))
    guild_names: set[str] = set()
    for value in deps.get("ALLOWED_GUILDS", []) or []:
        if isinstance(value, int) or str(value).strip().isdigit():
            guild_ids.add(int(value))
        elif str(value).strip():
            guild_names.add(_normalise_name(value))
    return guild_ids, guild_names


def _guild_is_allowed(guild: Any, deps: dict[str, Any] | Any) -> bool:
    """Return True when a guild is in the configured scope (or no scope is set)."""
    guild_ids, guild_names = _guild_filters(deps)
    if not guild_ids and not guild_names:
        return True

    guild_id = getattr(guild, "id", None)
    try:
        if guild_id is not None and int(guild_id) in guild_ids:
            return True
    except (TypeError, ValueError):
        pass

    return _normalise_name(getattr(guild, "name", "")) in guild_names


def _iter_guild_channels(guild: Any):
    """Yield channels that can own message threads for a guild."""
    text_channels = getattr(guild, "text_channels", None)
    forums = getattr(guild, "forums", None)
    if text_channels is not None or forums is not None:
        yield from text_channels or []
        yield from forums or []
        return

    yield from getattr(guild, "channels", []) or []


def _store_resolved_ids(deps: dict[str, Any] | Any, resolved: set[int]) -> None:
    """Persist the resolved channel IDs on either dependency container style."""
    resolved_list = sorted(resolved)
    try:
        deps["RESOLVED_ALLOWED_CHANNEL_IDS"] = resolved_list
    except (KeyError, TypeError):
        deps.resolved_allowed_channel_ids = resolved_list


def _scoped_guilds(
    bot: discord.Client,
    deps: dict[str, Any] | Any,
) -> list[Any]:
    """Return guilds that may contribute name matches.

    With no guild filter every guild the bot is in is searched. Configuring
    ``ALLOWED_GUILDS`` or ``ALLOWED_GUILD_IDS`` narrows the search to matches.
    """
    guilds = list(getattr(bot, "guilds", []) or [])
    guild_ids, guild_names = _guild_filters(deps)
    if guild_ids or guild_names:
        return [guild for guild in guilds if _guild_is_allowed(guild, deps)]
    return guilds


def _match_channel_ids(guilds: list[Any], names: set[str]) -> dict[str, list[int]]:
    """Map normalised channel names to IDs within the scoped guilds."""
    matches: dict[str, list[int]] = {}
    for guild in guilds:
        for channel in _iter_guild_channels(guild):
            channel_name = _normalise_name(getattr(channel, "name", ""))
            if channel_name not in names:
                continue
            try:
                matches.setdefault(channel_name, []).append(int(channel.id))
            except (TypeError, ValueError):
                continue
    return matches


def resolve_allowed_channel_names(
    bot: discord.Client,
    deps: dict[str, Any] | Any,
    logger: Any | None = None,
) -> set[int]:
    """Resolve configured channel names to IDs and store them for routing.

    Names are matched case-insensitively after stripping a leading ``#`` and
    surrounding whitespace. Names match in every guild the bot is in unless
    ``ALLOWED_GUILDS`` or ``ALLOWED_GUILD_IDS`` narrows the scope.
    """
    logger = logger or deps.get("logger")
    names = _configured_channel_names(deps)
    explicit_ids = _as_int_set(deps.get("ALLOWED_CHANNEL_IDS", []))

    if names and explicit_ids and logger is not None:
        logger.warning(
            "Both ALLOWED_CHANNEL_IDS and ALLOWED_CHANNELS are set; channel IDs "
            "take precedence and resolved names will be ignored for routing"
        )

    resolved: set[int] = set()
    if names:
        scoped_guilds = _scoped_guilds(bot, deps)
        guild_ids, guild_names = _guild_filters(deps)
        if logger is not None and not guild_ids and not guild_names:
            logger.info(
                "ALLOWED_CHANNELS names are matched across all %d guilds; set "
                "ALLOWED_GUILDS or ALLOWED_GUILD_IDS to narrow the search",
                len(scoped_guilds),
            )
        matches = _match_channel_ids(scoped_guilds, names)
        unmatched = [name for name in sorted(names) if name not in matches]
        for name in names - set(unmatched):
            resolved.update(matches[name])

        if logger is not None:
            logger.info(
                "Resolved ALLOWED_CHANNELS names %s to channel IDs %s",
                sorted(names),
                sorted(resolved),
            )
            if unmatched:
                logger.warning(
                    "ALLOWED_CHANNELS name(s) %s matched no channels in the configured scope",
                    unmatched,
                )

    _store_resolved_ids(deps, resolved)
    return resolved


def _allowed_channel_ids(
    deps: dict[str, Any] | Any,
    bot: discord.Client,
) -> set[int] | None:
    """Return the effective allowed IDs, or None when name fallback is needed."""
    explicit_ids = _as_int_set(deps.get("ALLOWED_CHANNEL_IDS", []))
    if explicit_ids:
        return explicit_ids

    if not _configured_channel_names(deps):
        return set()

    resolved = deps.get("RESOLVED_ALLOWED_CHANNEL_IDS", None)
    if resolved is not None:
        return _as_int_set(resolved)

    guilds = getattr(bot, "guilds", None)
    if guilds:
        return resolve_allowed_channel_names(bot, deps)
    return None


def _channel_allowed(
    channel: Any,
    deps: dict[str, Any] | Any,
    bot: discord.Client,
) -> bool:
    """Return True when a normal channel is in the configured allowlist."""
    allowed_ids = _allowed_channel_ids(deps, bot)
    if allowed_ids is not None:
        try:
            return int(channel.id) in allowed_ids
        except (TypeError, ValueError):
            return False

    # No guild list is available (for example in a focused unit test): fall
    # back to comparing the normalised name directly.
    if _normalise_name(getattr(channel, "name", "")) not in _configured_channel_names(deps):
        return False

    guild = getattr(channel, "guild", None)
    return guild is None or _guild_is_allowed(guild, deps)


def _thread_parent_allowed(
    thread: Any,
    deps: dict[str, Any] | Any,
    bot: discord.Client,
) -> bool:
    """Validate a thread using its parent channel, never the thread itself."""
    parent = getattr(thread, "parent", None)
    if parent is not None:
        return _channel_allowed(parent, deps, bot)

    parent_id = getattr(thread, "parent_id", None)
    if parent_id is None:
        return False

    allowed_ids = _allowed_channel_ids(deps, bot)
    if allowed_ids is None:
        return False
    try:
        return int(parent_id) in allowed_ids
    except (TypeError, ValueError):
        return False


def _is_thread(channel: Any) -> bool:
    thread_type = getattr(discord, "Thread", None)
    return bool(thread_type) and isinstance(channel, thread_type)


def _is_group_dm(channel: Any) -> bool:
    group_type = getattr(discord, "GroupChannel", None)
    return bool(group_type) and isinstance(channel, group_type)


def _mentions_bot(message: Any, bot: discord.Client) -> bool:
    """Return True when the message mentions the bot."""
    return bot.user in (getattr(message, "mentions", None) or [])


def _log_ignored(logger: Any, message: Any, reason: str) -> None:
    """Emit exactly one DEBUG reason line for a deliberately ignored message."""
    logger.debug(
        "Ignoring message %s: reason=%s",
        getattr(message, "id", "unknown"),
        reason,
    )


def _log_ignored_mention(
    logger: Any,
    message: Any,
    reason: str,
    hint: str | None = None,
) -> None:
    """Emit exactly one INFO line for a mention that routing deliberately drops."""
    author = getattr(message, "author", None)
    channel = getattr(message, "channel", None)
    suffix = f" ({hint})" if hint else ""
    logger.info(
        "Ignoring mention from %s %s in channel %s: reason=%s%s",
        "bot" if getattr(author, "bot", False) else "user",
        getattr(author, "id", "unknown"),
        getattr(channel, "id", "unknown"),
        reason,
        suffix,
    )


async def handle_incoming_message(
    message: discord.Message,
    deps: dict[str, Any] | Any,
    bot: discord.Client,
) -> None:
    """Handle incoming message with comprehensive routing and error handling."""
    logger = get_logger_with_context(deps["logger"], message)

    try:
        author = getattr(message, "author", None)
        if author == getattr(bot, "user", None):
            _log_ignored(logger, message, "self")
            return

        if getattr(author, "bot", False) is not True:
            conversation_manager = deps.get("conversation_manager")
            if conversation_manager is not None:
                is_dm = isinstance(message.channel, discord.DMChannel) or _is_group_dm(
                    message.channel
                )
                conversation_key = conversation_key_for_message(message, is_dm=is_dm)
                conversation_manager.reset_bot_streak(conversation_key=conversation_key)

        if isinstance(message.channel, discord.DMChannel) or _is_group_dm(message.channel):
            async with message.channel.typing():
                await process_dm_message(message, deps)
            return

        if not _mentions_bot(message, bot):
            _log_ignored(logger, message, "not_mentioned")
            return

        if _is_thread(message.channel):
            if not _thread_parent_allowed(message.channel, deps, bot):
                _log_ignored_mention(logger, message, "thread_parent_not_allowed")
                return
        elif not _channel_allowed(message.channel, deps, bot):
            _log_ignored_mention(logger, message, "channel_not_allowed")
            return

        async with message.channel.typing():
            await process_channel_message(message, deps)

    except Exception:
        logger.exception("Unhandled error in message routing")
        try:
            error_channels = (
                discord.DMChannel,
                discord.TextChannel,
                getattr(discord, "Thread", discord.TextChannel),
                getattr(discord, "GroupChannel", discord.DMChannel),
            )
            if isinstance(message.channel, error_channels):
                err_msg = "🔧 An unexpected error occurred. The issue has been logged."
                await message.channel.send(err_msg)
        except Exception:
            logger.exception("Failed to send error notification")
