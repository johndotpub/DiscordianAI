"""Thread-safe conversation history management for Discord bot.

This module provides a robust, thread-safe way to manage user conversation
histories, preventing race conditions when multiple messages are processed
concurrently from the same user.
"""

from collections.abc import Callable
import copy
import logging
import threading
import time
from typing import Any

from .config import DEFAULT_CONVERSATION_TTL_SECONDS

ConversationKey = int | str


def make_conversation_key(
    user_id: int | str,
    guild_id: int | str | None = None,
    channel_id: int | str | None = None,
) -> str:
    """Build a namespaced conversation key for a DM or guild channel/thread.

    Guild keys and DM keys use different prefixes, so they can never collide.
    Passing the channel id is enough to keep threads separate: a thread's own
    channel id is not its parent channel's id.
    """
    if guild_id is not None and channel_id is not None:
        return f"g:{guild_id}:c:{channel_id}"
    return f"dm:{user_id}"


def conversation_key_for_message(message: Any, *, is_dm: bool) -> str:
    """Return the conversation key for a Discord message."""
    author = getattr(message, "author", None)
    author_id = getattr(author, "id", None)

    if is_dm:
        return make_conversation_key(author_id)

    guild = getattr(message, "guild", None)
    guild_id = getattr(guild, "id", None)
    channel = getattr(message, "channel", None)
    channel_id = getattr(channel, "id", None)

    # Keep non-DM messages in the guild namespace even if a test double omits
    # guild context, so they still cannot collide with a DM conversation.
    if guild_id is None:
        guild_id = 0
    if channel_id is None:
        channel_id = 0

    return make_conversation_key(author_id, guild_id=guild_id, channel_id=channel_id)


class ThreadSafeConversationManager:
    """Thread-safe manager for user conversation histories.

    This class manages conversation state for Discord users in a thread-safe manner,
    preventing data corruption when multiple messages are processed concurrently.
    It uses fine-grained locking per user to maximize concurrency while ensuring
    data integrity.

    Thread Safety:
        - Uses threading.RLock for reentrant locking
        - Provides atomic operations for all conversation modifications
        - Returns deep copies to prevent external modification of internal state
    """

    def __init__(
        self,
        max_history_per_user: int = 50,
        cleanup_interval: int = 3600,
        conversation_ttl_seconds: int = DEFAULT_CONVERSATION_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
        *,
        ttl_seconds: int | None = None,
    ):
        """Initialize the conversation manager with thread-safe data structures.

        Args:
            max_history_per_user (int): Maximum conversation entries per user.
                                      Older entries are automatically pruned.
            cleanup_interval (int): How often to clean up inactive user locks (seconds).
            conversation_ttl_seconds (int): Idle seconds before a conversation and its
                                         lock are evicted. Non-positive values disable expiry.
            clock (Callable[[], float], optional): Time source used for TTL calculations.
            ttl_seconds (int, optional): Alias for conversation_ttl_seconds.
        """
        if ttl_seconds is not None:
            conversation_ttl_seconds = ttl_seconds

        self._conversations: dict[ConversationKey, list[dict[str, str]]] = {}
        self._user_locks: dict[ConversationKey, threading.RLock] = {}
        self._last_activity: dict[ConversationKey, float] = {}
        self._global_lock = threading.RLock()
        self._max_history = max_history_per_user
        self._cleanup_interval = cleanup_interval
        self._conversation_ttl = conversation_ttl_seconds
        self._clock = clock or time.time
        self._logger = logging.getLogger(f"{__name__}.ConversationManager")
        now = self._clock()
        self._last_cleanup = now
        self._last_expiry_sweep = now
        if conversation_ttl_seconds > 0:
            self._expiry_sweep_interval = max(
                0.001,
                min(float(cleanup_interval), conversation_ttl_seconds / 2.0),
            )
        else:
            self._expiry_sweep_interval = float("inf")

    @staticmethod
    def _resolve_key(
        user_id: ConversationKey | None,
        conversation_key: ConversationKey | None,
    ) -> ConversationKey:
        """Return the explicit conversation key, falling back to the legacy user id."""
        if conversation_key is not None:
            return conversation_key
        if user_id is None:
            msg = "Either user_id or conversation_key must be provided"
            raise ValueError(msg)
        return user_id

    def _get_user_lock(self, user_id: ConversationKey) -> threading.RLock:
        """Get or create a per-conversation lock for fine-grained concurrency control.

        Args:
            user_id (ConversationKey): The conversation key to get a lock for.

        Returns:
            threading.RLock: A reentrant lock specific to this conversation.
        """
        with self._global_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = threading.RLock()
            return self._user_locks[user_id]

    def _has_conversation_state(self, key: ConversationKey) -> bool:
        """Return True when a conversation or its lock is still registered."""
        with self._global_lock:
            return key in self._conversations or key in self._user_locks

    def _touch(self, key: ConversationKey) -> None:
        """Record that a conversation was just used."""
        with self._global_lock:
            self._last_activity[key] = self._clock()

    def _safe_cleanup(self) -> None:
        """Run due maintenance without letting cleanup failures break the caller."""
        try:
            self.cleanup_inactive_user_locks(force=False)
        except Exception as e:  # noqa: BLE001
            self._logger.warning("Background cleanup failed: %s", e)

    def _expire_stale_conversations(self, now: float) -> int:
        """Evict conversations idle longer than the TTL and drop their locks.

        The initial candidate scan takes the global lock only long enough to copy
        timestamps. Each candidate is then checked and removed under its own lock,
        so a large expired population does not hold up unrelated conversations.
        """
        if self._conversation_ttl <= 0:
            return 0

        cutoff = now - self._conversation_ttl
        with self._global_lock:
            candidates = [
                (key, last_seen, self._user_locks.get(key))
                for key, last_seen in self._last_activity.items()
                if last_seen < cutoff and key in self._conversations
            ]

        expired_count = 0
        removed_locks = 0
        for key, last_seen, lock in candidates:
            if lock is None:
                with self._global_lock:
                    if self._last_activity.get(key) != last_seen:
                        continue
                    if self._conversations.pop(key, None) is not None:
                        self._last_activity.pop(key, None)
                        expired_count += 1
                continue

            with lock, self._global_lock:
                if self._last_activity.get(key) != last_seen:
                    continue
                if self._conversations.pop(key, None) is not None:
                    self._last_activity.pop(key, None)
                    expired_count += 1
                if self._user_locks.get(key) is lock:
                    del self._user_locks[key]
                    removed_locks += 1

        if expired_count:
            self._logger.info(
                "Expired %d idle conversations (ttl=%ss)",
                expired_count,
                self._conversation_ttl,
            )

        return removed_locks

    def _remove_orphan_locks(self) -> int:
        """Remove locks that no longer have conversation data."""
        with self._global_lock:
            candidates = [
                (key, lock)
                for key, lock in self._user_locks.items()
                if key not in self._conversations
            ]

        removed_count = 0
        for key, lock in candidates:
            with lock, self._global_lock:
                if key in self._conversations:
                    continue
                if self._user_locks.get(key) is lock:
                    del self._user_locks[key]
                    self._last_activity.pop(key, None)
                    removed_count += 1

        return removed_count

    def cleanup_expired_conversations(self) -> int:
        """Immediately remove every conversation that has exceeded the TTL.

        Returns:
            int: Number of conversation locks removed.
        """
        now = self._clock()
        with self._global_lock:
            self._last_expiry_sweep = now
        return self._expire_stale_conversations(now)

    def get_conversation(
        self,
        user_id: ConversationKey | None = None,
        *,
        conversation_key: ConversationKey | None = None,
    ) -> list[dict[str, str]]:
        """Get a deep copy of the conversation history for a conversation key.

        Returns a copy to prevent external code from accidentally modifying
        the internal conversation state, which could cause race conditions.

        Args:
            user_id (ConversationKey): Legacy user ID fallback.
            conversation_key (ConversationKey): Explicit DM/channel conversation key.

        Returns:
            List[Dict[str, str]]: Deep copy of the conversation history.
                                 Each dict has 'role' and 'content' keys.
        """
        key = self._resolve_key(user_id, conversation_key)

        # Periodic cleanup of expired conversations and inactive locks.
        self._safe_cleanup()

        if not self._has_conversation_state(key):
            return []

        user_lock = self._get_user_lock(key)
        with user_lock:
            conversation = self._conversations.get(key, [])
            result = copy.deepcopy(conversation)
            if key in self._conversations:
                self._touch(key)
            self._logger.debug(
                "Retrieved conversation for %s: %d messages",
                key,
                len(result),
            )
            return result

    def add_message(
        self,
        user_id: ConversationKey | None = None,
        role: str | None = None,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        conversation_key: ConversationKey | None = None,
    ) -> None:
        """Add a message to a conversation history in a thread-safe manner.

        Automatically prunes old messages if the history exceeds max_history_per_user.

        Args:
            user_id (ConversationKey): Legacy user ID fallback.
            role (str): The message role ('user', 'assistant', or 'system').
            content (str): The message content.
            metadata (Dict[str, Any], optional): Additional metadata (e.g., AI service used).
            conversation_key (ConversationKey): Explicit DM/channel conversation key.

        Raises:
            ValueError: If role is not one of the expected values.
        """
        key = self._resolve_key(user_id, conversation_key)
        self._safe_cleanup()
        content = content or ""

        if role not in ["user", "assistant", "system"]:
            msg = f"Invalid role '{role}'. Must be 'user', 'assistant', or 'system'"
            raise ValueError(msg)

        # Allow empty content only if we have meaningful metadata (e.g., embed data).
        # Assistant turns are never valid without text: storing one creates an
        # orphan response that can never be paired with a question.
        if not content.strip() and (role == "assistant" or not metadata):
            self._logger.warning(
                "Attempted to add empty %s message for %s",
                role,
                key,
            )
            return

        user_lock = self._get_user_lock(key)
        with user_lock:
            if key not in self._conversations:
                self._conversations[key] = []

            # Add the new message with metadata
            message_entry = {"role": role, "content": content.strip()}

            # Add metadata if provided
            if metadata:
                message_entry["metadata"] = metadata

            self._conversations[key].append(message_entry)

            # Prune old messages if history is too long
            if len(self._conversations[key]) > self._max_history:
                removed_count = len(self._conversations[key]) - self._max_history
                self._conversations[key] = self._conversations[key][-self._max_history :]
                self._logger.info(
                    "Pruned %d old messages for %s (keeping latest %d)",
                    removed_count,
                    key,
                    self._max_history,
                )

            self._touch(key)
            message_count = len(self._conversations[key])
            self._logger.debug(
                "Added %s message for %s: %d chars, total history: %d messages",
                role,
                key,
                len(content),
                message_count,
            )

    def update_conversation(
        self,
        user_id: ConversationKey | None = None,
        conversation: list[dict[str, str]] | None = None,
        *,
        conversation_key: ConversationKey | None = None,
    ) -> None:
        """Replace the entire conversation history for a conversation key.

        This method validates all messages in the conversation before updating.

        Args:
            user_id (ConversationKey): Legacy user ID fallback.
            conversation (List[Dict[str, str]]): The new conversation history.
                                               Each dict must have 'role' and 'content' keys.
            conversation_key (ConversationKey): Explicit DM/channel conversation key.

        Raises:
            ValueError: If any message in the conversation is invalid.
        """
        key = self._resolve_key(user_id, conversation_key)
        self._safe_cleanup()
        conversation = conversation or []

        # Validate conversation format before acquiring lock
        for i, msg in enumerate(conversation):
            if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                err_msg = f"Invalid message at index {i}: missing 'role' or 'content'"
                raise ValueError(err_msg)
            if msg["role"] not in ["user", "assistant", "system"]:
                role_err = f"Invalid role at index {i}: '{msg['role']}'"
                raise ValueError(role_err)

        user_lock = self._get_user_lock(key)
        with user_lock:
            # Deep copy to prevent external modifications
            self._conversations[key] = copy.deepcopy(conversation)

            # Apply length limit
            if len(self._conversations[key]) > self._max_history:
                removed_count = len(self._conversations[key]) - self._max_history
                self._conversations[key] = self._conversations[key][-self._max_history :]
                self._logger.info(
                    "Truncated conversation for %s: removed %d old messages",
                    key,
                    removed_count,
                )

            self._touch(key)
            self._logger.debug(
                "Updated full conversation for %s: %d messages",
                key,
                len(self._conversations[key]),
            )

    def clear_conversation(
        self,
        user_id: ConversationKey | None = None,
        *,
        conversation_key: ConversationKey | None = None,
    ) -> int:
        """Clear the conversation history for a conversation key.

        Args:
            user_id (ConversationKey): Legacy user ID fallback.
            conversation_key (ConversationKey): Explicit DM/channel conversation key.

        Returns:
            int: Number of messages that were cleared.
        """
        key = self._resolve_key(user_id, conversation_key)
        self._safe_cleanup()
        if not self._has_conversation_state(key):
            return 0

        user_lock = self._get_user_lock(key)
        with user_lock:
            cleared_count = len(self._conversations.get(key, []))
            self._conversations.pop(key, None)
            with self._global_lock:
                self._last_activity.pop(key, None)

            self._logger.info(
                "Cleared conversation for %s: %d messages removed",
                key,
                cleared_count,
            )
            return cleared_count

    def get_conversation_summary(
        self,
        user_id: ConversationKey | None = None,
        *,
        conversation_key: ConversationKey | None = None,
    ) -> tuple[int, str | None, str | None]:
        """Get a summary of the conversation state.

        Args:
            user_id (ConversationKey): Legacy user ID fallback.
            conversation_key (ConversationKey): Explicit DM/channel conversation key.

        Returns:
            Tuple[int, Optional[str], Optional[str]]:
                (message_count, last_user_message, last_assistant_message)
        """
        key = self._resolve_key(user_id, conversation_key)
        self._safe_cleanup()
        if not self._has_conversation_state(key):
            return 0, None, None

        user_lock = self._get_user_lock(key)
        with user_lock:
            conversation = self._conversations.get(key, [])
            if key in self._conversations:
                self._touch(key)
            message_count = len(conversation)

            last_user_msg = None
            last_assistant_msg = None

            # Find most recent messages by role
            for msg in reversed(conversation):
                if msg["role"] == "user" and last_user_msg is None:
                    last_user_msg = msg["content"]
                elif msg["role"] == "assistant" and last_assistant_msg is None:
                    last_assistant_msg = msg["content"]

                if last_user_msg and last_assistant_msg:
                    break

            return message_count, last_user_msg, last_assistant_msg

    def get_recent_ai_service(
        self,
        user_id: ConversationKey | None = None,
        lookback_messages: int = 6,
        *,
        conversation_key: ConversationKey | None = None,
    ) -> str | None:
        """Get the AI service used in recent assistant messages for consistency routing.

        Args:
            user_id (ConversationKey): Legacy user ID fallback.
            lookback_messages (int): Number of recent messages to examine. Values
                less than one disable the lookup.
            conversation_key (ConversationKey): Explicit DM/channel conversation key.

        Returns:
            Optional[str]: The AI service ('openai' or 'perplexity') used recently, or None.
        """
        key = self._resolve_key(user_id, conversation_key)
        self._safe_cleanup()
        if not self._has_conversation_state(key):
            return None

        user_lock = self._get_user_lock(key)
        with user_lock:
            conversation = self._conversations.get(key, [])

            if lookback_messages <= 0:
                if key in self._conversations:
                    self._touch(key)
                return None

            # Look at recent messages in reverse chronological order
            recent_messages = (
                conversation[-lookback_messages:]
                if len(conversation) > lookback_messages
                else conversation
            )

            service = None
            # Find the most recent assistant message with AI service metadata
            for msg in reversed(recent_messages):
                if (
                    msg.get("role") == "assistant"
                    and msg.get("metadata")
                    and msg["metadata"].get("ai_service")
                ):
                    service = msg["metadata"]["ai_service"]
                    break

            if key in self._conversations:
                self._touch(key)
            return service

    def get_conversation_summary_formatted(
        self,
        user_id: ConversationKey | None = None,
        *,
        conversation_key: ConversationKey | None = None,
    ) -> list[dict[str, str]]:
        """Generate a conversation summary by pairing user and assistant messages.

        Creates a structured summary of the conversation by pairing user messages
        with their corresponding assistant responses in chronological order.
        This helps provide relevant context to AI models while managing token usage.

        Args:
            user_id (ConversationKey): Legacy user ID fallback.
            conversation_key (ConversationKey): Explicit DM/channel conversation key.

        Returns:
            List[Dict[str, str]]: Summarized conversation with paired messages.
                                 Maintains chronological order with user messages
                                 paired to their assistant responses.

        Note:
            - User messages without corresponding assistant responses are included
            - Assistant messages without an immediately preceding user message are filtered out
            - This helps maintain conversational flow while reducing token usage
        """
        key = self._resolve_key(user_id, conversation_key)
        self._safe_cleanup()
        if not self._has_conversation_state(key):
            return []

        user_lock = self._get_user_lock(key)
        with user_lock:
            conversation = self._conversations.get(key, [])
            if key in self._conversations:
                self._touch(key)

            if not conversation:
                return []

            summary = []

            # Walk the transcript in order. An assistant entry is only valid
            # when the last entry emitted was a user entry, so an orphan
            # response can never shift every later answer onto the wrong
            # question. Consecutive user entries and a trailing unanswered
            # question are preserved.
            for msg in conversation:
                role = msg["role"]
                if role == "user":
                    summary.append({"role": "user", "content": msg["content"]})
                elif role == "assistant" and summary and summary[-1]["role"] == "user":
                    summary.append({"role": "assistant", "content": msg["content"]})

            self._logger.debug(
                "Generated conversation summary for %s: %d messages",
                key,
                len(summary),
            )
            return summary

    def get_all_user_ids(self) -> list[ConversationKey]:
        """Get a list of all conversation keys with history.

        Returns:
            List[ConversationKey]: Conversation keys that have history.
        """
        self._safe_cleanup()
        with self._global_lock:
            return list(self._conversations.keys())

    def get_stats(self) -> dict[str, int]:
        """Get statistics about the conversation manager state.

        Returns:
            Dict[str, int]: Statistics including user count, total messages, etc.
        """
        self._safe_cleanup()
        with self._global_lock:
            total_messages = sum(len(conv) for conv in self._conversations.values())
            return {
                "total_users": len(self._conversations),
                "total_messages": total_messages,
                "average_messages_per_user": (
                    total_messages / len(self._conversations) if self._conversations else 0
                ),
                "active_locks": len(self._user_locks),
            }

    def get_memory_stats(self) -> dict[str, Any]:
        """Get memory usage statistics for monitoring.

        Returns:
            Dictionary with memory usage statistics
        """
        self._safe_cleanup()
        with self._global_lock:
            total_messages = sum(len(conv) for conv in self._conversations.values())
            return {
                "total_users": len(self._conversations),
                "total_locks": len(self._user_locks),
                "total_messages": total_messages,
                "max_history_per_user": self._max_history,
                "average_messages_per_user": (
                    total_messages / len(self._conversations) if self._conversations else 0
                ),
            }

    def cleanup_inactive_user_locks(self, force: bool = False) -> int:
        """Clean up expired conversations and inactive user locks.

        Expiry uses the conversation TTL and its own sweep cadence. Orphaned locks
        keep using the configured cleanup interval.

        Args:
            force (bool): If True, runs cleanup regardless of timing. If False, only runs
                         the parts that are due.

        Returns:
            int: Number of user locks that were cleaned up.
        """
        current_time = self._clock()

        with self._global_lock:
            if force:
                expire_due = True
                cleanup_due = True
            else:
                expire_due = (
                    self._expiry_sweep_interval != float("inf")
                    and current_time - self._last_expiry_sweep >= self._expiry_sweep_interval
                )
                cleanup_due = (current_time - self._last_cleanup) >= self._cleanup_interval

            if not expire_due and not cleanup_due:
                return 0

            if expire_due:
                self._last_expiry_sweep = current_time
            if cleanup_due:
                self._last_cleanup = current_time

        removed_count = 0
        if expire_due:
            removed_count += self._expire_stale_conversations(current_time)
        if cleanup_due:
            orphan_count = self._remove_orphan_locks()
            removed_count += orphan_count
            if orphan_count:
                self._logger.info(
                    "Cleaned up %d inactive user locks for memory optimization",
                    orphan_count,
                )

        return removed_count
