import asyncio


async def process_input_message(
    input_message: str,
    user,
    conversation_summary: list[dict],
    conversation_history: dict,
    logger,
    client,
    gpt_model: str,
    system_message: str,
    output_tokens: int,
    to_thread=asyncio.to_thread,
) -> str:
    logger.info("Sending prompt to the API.")
    conversation = conversation_history.get(user.id, [])
    conversation.append({"role": "user", "content": input_message})

    def call_openai_api():
        logger.debug(f"GPT_MODEL: {gpt_model}")
        logger.debug(f"SYSTEM_MESSAGE: {system_message}")
        logger.debug(f"conversation_summary: {conversation_summary}")
        logger.debug(f"input_message: {input_message}")
        return client.chat.completions.create(
            model=gpt_model,
            messages=[
                {"role": "system", "content": system_message},
                *conversation_summary,
                {"role": "user", "content": input_message},
            ],
            max_tokens=output_tokens,
            temperature=0.7,
        )

    try:
        response = await to_thread(call_openai_api)
        logger.debug(f"Full API response: {response}")
        if response.choices:
            response_content = response.choices[0].message.content.strip()
        else:
            response_content = None
    except Exception as e:
        logger.error(f"Failed to get response from the API: {e}")
        return "Sorry, an error occurred while processing the message."
    if response_content:
        logger.info("Received response from the API.")
        logger.info(f"Sent the response: {response_content}")
        conversation.append({"role": "assistant", "content": response_content})
        conversation_history[user.id] = conversation
        return response_content
    else:
        logger.error("API error: No response text.")
        return "Sorry, I didn't get that. Can you rephrase or ask again?"
