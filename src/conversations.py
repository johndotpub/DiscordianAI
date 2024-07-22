
# Define the function to get the conversation summary
def get_conversation_summary(conversation: list[dict]) -> list[dict]:
    """
    Conversation summary from combining user messages and assistant responses
    """
    try:
        summary = []
        user_messages = [
            message for message in conversation if message["role"] == "user"
        ]
        assistant_responses = [
            message for message in conversation if message["role"] == "assistant"
        ]

        # Combine user messages and assistant responses into a summary
        for user_message, assistant_response in zip(
            user_messages, assistant_responses
        ):
            summary.append(user_message)
            summary.append(assistant_response)

        return summary
    except Exception as e:
        logger.error(f"Error getting conversation summary: {e}")
        raise