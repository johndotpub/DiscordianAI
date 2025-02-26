def get_conversation_summary(conversation: list[dict]) -> list[dict]:
    """
    Get a summary of the conversation.

    Args:
        conversation (list[dict]): The conversation history.

    Returns:
        list[dict]: The summarized conversation.
    """
    summary = []
    user_messages = [msg for msg in conversation if msg["role"] == "user"]
    assistant_responses = [msg for msg in conversation if msg["role"] == "assistant"]

    for user_msg, assistant_resp in zip(user_messages, assistant_responses):
        summary.append(user_msg)
        summary.append(assistant_resp)

    return summary
