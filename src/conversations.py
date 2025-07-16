def get_conversation_summary(conversation: list[dict]) -> list[dict]:
    """
    Get a summary of the conversation.

    Args:
        conversation (list[dict]): The conversation history. Must not be None.

    Returns:
        list[dict]: The summarized conversation.

    Raises:
        ValueError: If conversation is None.
    """
    if conversation is None:
        raise ValueError("conversation must not be None")
    summary = []
    user_messages = [msg for msg in conversation if msg["role"] == "user"]
    assistant_responses = [msg for msg in conversation if msg["role"] == "assistant"]

    for user_msg, assistant_resp in zip(user_messages, assistant_responses):
        summary.append(user_msg)
        summary.append(assistant_resp)

    # Include any unmatched user messages in the summary
    if len(user_messages) > len(assistant_responses):
        summary.extend(user_messages[len(assistant_responses) :])
    return summary
