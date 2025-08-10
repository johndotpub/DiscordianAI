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
        self._conversations: dict[int, list[dict[str, str]]] = {}
        self._user_locks: dict[int, threading.RLock] = {}
        self._global_lock = threading.RLock()
        self._max_history = max_history_per_user
        self._cleanup_interval = cleanup_interval
        self._logger = logging.getLogger(f"{__name__}.ConversationManager")
        self._last_cleanup = time.time()

    def _get_user_lock(self, user_id: int) -> threading.RLock:
        """Get or create a per-user lock for fine-grained concurrency control.

        Args:
            user_id (int): The user ID to get a lock for.

        Returns:
            threading.RLock: A reentrant lock specific to this user.
        """
        with self._global_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = threading.RLock()
            return self._user_locks[user_id]

    def get_conversation(self, user_id: int) -> list[dict[str, str]]:
        """Get a deep copy of the conversation history for a user.

        Returns a copy to prevent external code from accidentally modifying
        the internal conversation state, which could cause race conditions.

        Args:
            user_id (int): The Discord user ID.

        Returns:
            List[Dict[str, str]]: Deep copy of the user's conversation history.
                                 Each dict has 'role' and 'content' keys.
        """
        # Periodic cleanup of inactive locks (non-blocking)
        try:
            self.cleanup_inactive_user_locks(force=False)
        except Exception as e:
            self._logger.warning(f"Background cleanup failed: {e}")

        user_lock = self._get_user_lock(user_id)
        with user_lock:
            conversation = self._conversations.get(user_id, [])
            result = copy.deepcopy(conversation)
            self._logger.debug(
                f"Retrieved conversation for user {user_id}: {len(result)} messages"
            )
            return result

    def add_message(
        self, user_id: int, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Add a message to the user's conversation history in a thread-safe manner.

        Automatically prunes old messages if the history exceeds max_history_per_user.

        Args:
            user_id (int): The Discord user ID.
            role (str): The message role ('user', 'assistant', or 'system').
            content (str): The message content.
            metadata (Dict[str, Any], optional): Additional metadata (e.g., AI service used).

        Raises:
            ValueError: If role is not one of the expected values.
        """
        if role not in ["user", "assistant", "system"]:
            raise ValueError(f"Invalid role '{role}'. Must be 'user', 'assistant', or 'system'")

        if not content.strip():
            self._logger.warning(f"Attempted to add empty message for user {user_id}")
            return

        user_lock = self._get_user_lock(user_id)
        with user_lock:
            if user_id not in self._conversations:
                self._conversations[user_id] = []

            # Add the new message with metadata
            message_entry = {"role": role, "content": content.strip()}

            # Add metadata if provided
            if metadata:
                message_entry["metadata"] = metadata

            self._conversations[user_id].append(message_entry)

            # Prune old messages if history is too long
            if len(self._conversations[user_id]) > self._max_history:
                removed_count = len(self._conversations[user_id]) - self._max_history
                self._conversations[user_id] = self._conversations[user_id][-self._max_history :]
                self._logger.info(
                    f"Pruned {removed_count} old messages for user {user_id} "
                    f"(keeping latest {self._max_history})"
                )

            message_count = len(self._conversations[user_id])
            self._logger.debug(
                f"Added {role} message for user {user_id}: {len(content)} chars, "
                f"total history: {message_count} messages"
            )

    def update_conversation(self, user_id: int, conversation: list[dict[str, str]]) -> None:
        """Replace the entire conversation history for a user in a thread-safe manner.

        This method validates all messages in the conversation before updating.

        Args:
            user_id (int): The Discord user ID.
            conversation (List[Dict[str, str]]): The new conversation history.
                                               Each dict must have 'role' and 'content' keys.

        Raises:
            ValueError: If any message in the conversation is invalid.
        """
        # Validate conversation format before acquiring lock
        for i, msg in enumerate(conversation):
            if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                raise ValueError(f"Invalid message at index {i}: missing 'role' or 'content'")
            if msg["role"] not in ["user", "assistant", "system"]:
                raise ValueError(f"Invalid role at index {i}: '{msg['role']}'")

        user_lock = self._get_user_lock(user_id)
        with user_lock:
            # Deep copy to prevent external modifications
            self._conversations[user_id] = copy.deepcopy(conversation)

            # Apply length limit
            if len(self._conversations[user_id]) > self._max_history:
                removed_count = len(self._conversations[user_id]) - self._max_history
                self._conversations[user_id] = self._conversations[user_id][-self._max_history :]
                self._logger.info(
                    f"Truncated conversation for user {user_id}: "
                    f"removed {removed_count} old messages"
                )

            self._logger.debug(
                f"Updated full conversation for user {user_id}: "
                f"{len(self._conversations[user_id])} messages"
            )

    def clear_conversation(self, user_id: int) -> int:
        """Clear the conversation history for a user.

        Args:
            user_id (int): The Discord user ID.

        Returns:
            int: Number of messages that were cleared.
        """
        user_lock = self._get_user_lock(user_id)
        with user_lock:
            cleared_count = len(self._conversations.get(user_id, []))
            self._conversations.pop(user_id, None)

            self._logger.info(
                f"Cleared conversation for user {user_id}: {cleared_count} messages removed"
            )
            return cleared_count

    def get_conversation_summary(self, user_id: int) -> tuple[int, str | None, str | None]:
        """Get a summary of the user's conversation state.

        Args:
            user_id (int): The Discord user ID.

        Returns:
            Tuple[int, Optional[str], Optional[str]]:
                (message_count, last_user_message, last_assistant_message)
        """
        user_lock = self._get_user_lock(user_id)
        with user_lock:
            conversation = self._conversations.get(user_id, [])
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

    def get_recent_ai_service(self, user_id: int, lookback_messages: int = 6) -> str | None:
        """Get the AI service used in recent assistant messages for consistency routing.

        Args:
            user_id (int): The Discord user ID.
            lookback_messages (int): Number of recent messages to examine.

        Returns:
            Optional[str]: The AI service ('openai' or 'perplexity') used recently, or None.
        """
        user_lock = self._get_user_lock(user_id)
        with user_lock:
            conversation = self._conversations.get(user_id, [])

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

    def get_conversation_summary_formatted(self, user_id: int) -> list[dict[str, str]]:
        """Generate a conversation summary by pairing user and assistant messages.

        Creates a structured summary of the conversation by pairing user messages
        with their corresponding assistant responses in chronological order.
        This helps provide relevant context to AI models while managing token usage.

        Args:
            user_id (int): The Discord user ID.

        Returns:
            List[Dict[str, str]]: Summarized conversation with paired messages.
                                 Maintains chronological order with user messages
                                 paired to their assistant responses.

        Note:
            - User messages without corresponding assistant responses are included
            - Assistant messages without preceding user messages are filtered out
            - This helps maintain conversational flow while reducing token usage
        """
        user_lock = self._get_user_lock(user_id)
        with user_lock:
            conversation = self._conversations.get(user_id, [])

            if not conversation:
                return []

            summary = []

            # Extract messages by role for pairing (strip metadata for AI context)
            user_messages = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in conversation
                if msg["role"] == "user"
            ]
            assistant_responses = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in conversation
                if msg["role"] == "assistant"
            ]

            # Pair user messages with assistant responses chronologically
            for user_msg, assistant_resp in zip(user_messages, assistant_responses, strict=False):
                summary.append(user_msg)
                summary.append(assistant_resp)

            # Include any unpaired user messages at the end
            if len(user_messages) > len(assistant_responses):
                summary.extend(user_messages[len(assistant_responses) :])

            self._logger.debug(
                f"Generated conversation summary for user {user_id}: {len(summary)} messages"
            )
            return summary

    def get_all_user_ids(self) -> list[int]:
        """Get a list of all user IDs with conversation history.

        Returns:
            List[int]: List of user IDs that have conversation history.
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

    def cleanup_inactive_user_locks(self, force: bool = False) -> int:
        """Clean up locks for users with no conversation history to prevent memory leaks.

        This method is automatically called periodically, but can be forced to run immediately.
        Only cleans up locks for users who have no conversation data.

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
            inactive_user_ids = []
            for user_id in list(self._user_locks.keys()):
                if user_id not in self._conversations:
                    inactive_user_ids.append(user_id)

            # Remove inactive user locks
            for user_id in inactive_user_ids:
                del self._user_locks[user_id]

            self._last_cleanup = current_time

            if inactive_user_ids:
                self._logger.info(
                    f"Cleaned up {len(inactive_user_ids)} inactive user locks "
                    f"for memory optimization"
                )

            return len(inactive_user_ids)
