"""OpenAI API processing with thread-safe conversation management and enhanced error handling.

This module handles all OpenAI API interactions including GPT-5 specific parameters,
conversation state management, and comprehensive error recovery.
"""

import asyncio
import logging

from .caching import cached_response, deduplicated_request
from .config import DEFAULT_CACHE_TTL
from .conversation_manager import ThreadSafeConversationManager
from .error_handling import RetryConfig, retry_with_backoff


@cached_response(ttl=DEFAULT_CACHE_TTL)
@deduplicated_request()  # Prevent duplicate simultaneous requests
async def process_openai_message(
    message: str,
    user,
    conversation_summary: list[dict],
    conversation_manager: ThreadSafeConversationManager,
    logger: logging.Logger,
    openai_client,
    gpt_model: str,
    system_message: str,
    output_tokens: int,
) -> str | None:
    """Process message using OpenAI API with thread-safe conversation management.

    Handles conversation state updates, API calls, error recovery, and
    GPT integration in a production-ready manner.

    Args:
        message (str): User's input message
        user: Discord user object
        conversation_summary (list[dict]): Conversation summary for context
        conversation_manager (ThreadSafeConversationManager): Thread-safe conversation manager
        logger (logging.Logger): Logger for API events
        openai_client: OpenAI client instance
        gpt_model (str): GPT model identifier (e.g., 'gpt-5', 'gpt-4')
        system_message (str): System prompt for the AI
        output_tokens (int): Maximum tokens to generate

    Returns:
        Optional[str]: Generated response text, or None if generation failed

    Side Effects:
        - Updates user's conversation history via thread-safe manager
        - Logs API calls and responses
        - Handles rate limiting and error recovery
    """
    try:
        logger.info(f"Processing OpenAI request for user {user.id} with model {gpt_model}")

        # Note: We'll add user message to conversation history only after successful response
        # to maintain consistency and allow rollback on failures

        # Build API parameters dynamically (only officially supported parameters)
        api_params = {
            "model": gpt_model,
            "messages": [
                {"role": "system", "content": system_message},
                *conversation_summary,
                {"role": "user", "content": message},
            ],
            "max_tokens": output_tokens,
        }

        logger.debug(f"Making OpenAI API call with {len(api_params['messages'])} messages")
        logger.debug(f"API parameters: {api_params}")

        # Define the API call function for retry
        async def api_call_with_retry():
            return await asyncio.to_thread(
                lambda: openai_client.chat.completions.create(**api_params)
            )

        # Make API call with enhanced error handling and retries
        logger.debug("Executing OpenAI API call with retry logic")
        retry_config = RetryConfig(max_attempts=2, base_delay=1.0, max_delay=30.0)

        try:
            response = await retry_with_backoff(api_call_with_retry, retry_config, logger)
        except Exception:
            logger.exception("OpenAI API call failed after retries")
            return None
    except TimeoutError:
        logger.exception(f"OpenAI API call timed out for user {user.id}")
        return None
    except Exception:
        logger.exception("OpenAI API call failed for user %s", user.id)

        # Log additional context for debugging
        logger.debug(
            f"Failed API call context - Model: {gpt_model}, Message length: {len(message)}"
        )

        # Don't add failed responses to conversation history
        return None
    else:
        # Log response metadata
        logger.debug(f"OpenAI API response received - ID: {getattr(response, 'id', 'unknown')}")
        if hasattr(response, "usage"):
            usage = response.usage
            logger.info(
                f"Token usage - Prompt: {getattr(usage, 'prompt_tokens', 'unknown')}, "
                f"Completion: {getattr(usage, 'completion_tokens', 'unknown')}, "
                f"Total: {getattr(usage, 'total_tokens', 'unknown')}"
            )

        # Extract and validate response
        if response.choices and response.choices[0].message.content:
            response_content = response.choices[0].message.content.strip()

            if not response_content:
                logger.warning("OpenAI returned empty response content")
                return None

            logger.info(
                f"OpenAI response generated successfully: {len(response_content)} characters, "
                f"finish_reason: {getattr(response.choices[0], 'finish_reason', 'unknown')}"
            )
            logger.debug(f"Response preview: {response_content[:200]}...")

            # Add both user and assistant messages to conversation history (thread-safe)
            # Only add after successful response to maintain consistency
            conversation_manager.add_message(user.id, "user", message)
            conversation_manager.add_message(
                user.id,
                "assistant",
                response_content,
                metadata={"ai_service": "openai", "model": gpt_model},
            )

            return response_content

        logger.error(f"OpenAI API returned invalid response structure: {response}")
        return None
