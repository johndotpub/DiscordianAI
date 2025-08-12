"""Conversation history summarization and processing utilities.

This module provides functions for processing and summarizing conversation
histories to provide appropriate context for AI model requests while
managing token limits and conversation flow.
"""


def get_conversation_summary(conversation: list[dict[str, str]]) -> list[dict[str, str]]:
    """Generate a conversation summary by pairing user and assistant messages.

    Creates a structured summary of the conversation by pairing user messages
    with their corresponding assistant responses in chronological order.
    This helps provide relevant context to AI models while managing token usage.

    Args:
        conversation (List[Dict[str, str]]): The full conversation history.
                                           Each dict must have 'role' and 'content' keys.
                                           Roles should be 'user' or 'assistant'.

    Returns:
        List[Dict[str, str]]: Summarized conversation with paired messages.
                             Maintains chronological order with user messages
                             paired to their assistant responses.

    Raises:
        ValueError: If conversation is None (explicit validation for safety)

    Examples:
        >>> conversation = [
        ...     {"role": "user", "content": "Hello"},
        ...     {"role": "assistant", "content": "Hi there!"},
        ...     {"role": "user", "content": "How are you?"}
        ... ]
        >>> summary = get_conversation_summary(conversation)
        >>> len(summary)  # Returns paired messages + unpaired user messages
        3

    Note:
        - User messages without corresponding assistant responses are included
        - Assistant messages without preceding user messages are filtered out
        - This helps maintain conversational flow while reducing token usage
    """
    if conversation is None:
        raise ValueError("conversation must not be None")

    summary = []

    # Extract messages by role for pairing
    user_messages = [msg for msg in conversation if msg["role"] == "user"]
    assistant_responses = [msg for msg in conversation if msg["role"] == "assistant"]

    # Pair user messages with assistant responses chronologically
    for user_msg, assistant_resp in zip(user_messages, assistant_responses, strict=False):
        summary.append(user_msg)
        summary.append(assistant_resp)

    # Include any unpaired user messages at the end
    # (These represent questions that haven't been answered yet)
    if len(user_messages) > len(assistant_responses):
        summary.extend(user_messages[len(assistant_responses) :])

    return summary
