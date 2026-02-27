"""OpenAI API processing with thread-safe conversation management and enhanced error handling.

This module handles all OpenAI API interactions including GPT-5 specific parameters,
conversation state management, and comprehensive error recovery.
"""

from .caching import cached_response, deduplicated_request
from .config import DEFAULT_CACHE_TTL
from .error_handling import RetryConfig, retry_with_backoff
from .models import AIRequest, OpenAIConfig


@cached_response(ttl=DEFAULT_CACHE_TTL)
@deduplicated_request()
async def process_openai_message(
    request: AIRequest,
    conversation_summary: list[dict],
    openai_client,
    config: OpenAIConfig,
) -> str | None:
    """Process message using OpenAI API with thread-safe conversation management."""
    try:
        # Build API parameters dynamically
        api_params = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": config.system_message},
                *conversation_summary,
                {"role": "user", "content": request.message},
            ],
            "max_completion_tokens": config.output_tokens,
        }
        # GPT-5 frontier models use fixed sampling and ignore temperature overrides.

        request.logger.debug(
            "Making OpenAI API call with %d messages", len(api_params["messages"])
        )

        # Define the API call function for retry
        async def api_call_with_retry():
            return await openai_client.chat.completions.create(**api_params)

        # Make API call with enhanced error handling and retries
        retry_config = RetryConfig(max_attempts=2, base_delay=1.0, max_delay=30.0)

        try:
            response = await retry_with_backoff(api_call_with_retry, retry_config, request.logger)
        except Exception:
            request.logger.exception("OpenAI API call failed after retries")
            return None

    except TimeoutError:
        request.logger.exception("OpenAI API call timed out for user %s", request.user.id)
        return None
    except Exception:
        request.logger.exception("OpenAI API call failed for user %s", request.user.id)
        return None
    else:
        # Extract and validate response
        if response.choices and response.choices[0].message.content:
            response_content = response.choices[0].message.content.strip()

            if not response_content:
                request.logger.warning("OpenAI returned empty response content")
                return None

            request.logger.info(
                "OpenAI response generated successfully: %d characters, finish_reason: %s",
                len(response_content),
                getattr(response.choices[0], "finish_reason", "unknown"),
            )

            # Add both user and assistant messages to conversation history (thread-safe)
            # Only add after successful response to maintain consistency
            request.conversation_manager.add_message(request.user.id, "user", request.message)
            request.conversation_manager.add_message(
                request.user.id,
                "assistant",
                response_content,
                metadata={"ai_service": "openai", "model": config.model},
            )

            return response_content

        request.logger.error("OpenAI API returned invalid response structure: %s", response)
        return None
