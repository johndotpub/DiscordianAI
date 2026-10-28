"""Thread-safe conversation history management for Discord bot.

This module provides a robust, thread-safe way to manage user conversation
histories, preventing race conditions when multiple messages are processed
concurrently from the same user.
"""

import copy
import logging
import threading
import time
from typing import Any

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

    def __init__(self, max_history_per_user: int = 50, cleanup_interval: int = 3600):
        """Initialize the conversation manager with thread-safe data structures.

        Args:
            max_history_per_user (int): Maximum conversation entries per user.
                                      Older entries are automatically pruned.
            cleanup_interval (int): How often to clean up inactive user locks (seconds).
        """
        self._conversations: dict[ConversationKey, list[dict[str, str]]] = {}
        self._user_locks: dict[ConversationKey, threading.RLock] = {}
        self._global_lock = threading.RLock()
        self._max_history = max_history_per_user
        self._cleanup_interval = cleanup_interval
        self._logger = logging.getLogger(f"{__name__}.ConversationManager")
        self._last_cleanup = time.time()

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

    def _get_conversation_lock(self, conversation_key: ConversationKey) -> threading.RLock:
        """Alias for :meth:`_get_user_lock` using conversation-key terminology."""
        return self._get_user_lock(conversation_key)

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

        # Periodic cleanup of inactive locks (non-blocking)
        try:
            self.cleanup_inactive_user_locks(force=False)
        except Exception as e:  # noqa: BLE001
            self._logger.warning("Background cleanup failed: %s", e)

        user_lock = self._get_user_lock(key)
        with user_lock:
            conversation = self._conversations.get(key, [])
            result = copy.deepcopy(conversation)
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
        user_lock = self._get_user_lock(key)
        with user_lock:
            cleared_count = len(self._conversations.get(key, []))
            self._conversations.pop(key, None)

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
        user_lock = self._get_user_lock(key)
        with user_lock:
            conversation = self._conversations.get(key, [])
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
            lookback_messages (int): Number of recent messages to examine.
            conversation_key (ConversationKey): Explicit DM/channel conversation key.

        Returns:
            Optional[str]: The AI service ('openai' or 'perplexity') used recently, or None.
        """
        key = self._resolve_key(user_id, conversation_key)
        user_lock = self._get_user_lock(key)
        with user_lock:
            conversation = self._conversations.get(key, [])

            # Look at recent messages in reverse chronological order
            recent_messages = (
                conversation[-lookback_messages:]
                if len(conversation) > lookback_messages
                else conversation
            )

            # Find the most recent assistant message with AI service metadata
            for msg in reversed(recent_messages):
                if (
                    msg.get("role") == "assistant"
                    and msg.get("metadata")
                    and msg["metadata"].get("ai_service")
                ):
                    return msg["metadata"]["ai_service"]

            return None

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
        user_lock = self._get_user_lock(key)
        with user_lock:
            conversation = self._conversations.get(key, [])

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
        with self._global_lock:
            return list(self._conversations.keys())

    def get_stats(self) -> dict[str, int]:
        """Get statistics about the conversation manager state.

        Returns:
            Dict[str, int]: Statistics including user count, total messages, etc.
        """
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
        """Clean up inactive user locks to prevent memory leaks.

        Args:
            force (bool): If True, runs cleanup regardless of timing. If False, only runs
                         if enough time has passed since last cleanup.

        Returns:
            int: Number of user locks that were cleaned up.
        """
        current_time = time.time()

        # Only run cleanup at configured interval unless forced
        if not force and (current_time - self._last_cleanup) < self._cleanup_interval:
            return 0

        with self._global_lock:
            # Find user locks that have no corresponding conversation data
            inactive_user_ids = [
                user_id
                for user_id in list(self._user_locks.keys())
                if user_id not in self._conversations
            ]

            # Remove inactive user locks
            for user_id in inactive_user_ids:
                del self._user_locks[user_id]

            self._last_cleanup = current_time

            if inactive_user_ids:
                self._logger.info(
                    "Cleaned up %d inactive user locks for memory optimization",
                    len(inactive_user_ids),
                )

            return len(inactive_user_ids)
