"""OpenAI API processing with thread-safe conversation management and enhanced error handling.

This module handles all OpenAI API interactions including GPT-5 specific parameters,
conversation state management, and comprehensive error recovery.
"""

from .api_context import api_call
from .caching import cached_response, deduplicated_request
from .config import DEFAULT_CACHE_TTL
from .error_handling import DEFAULT_API_RETRY_CONFIG, retry_with_backoff
from .message_builder import build_messages
from .models import AIRequest, OpenAIConfig


def _build_openai_api_params(
    model: str,
    system: str,
    user_msg: str,
    tokens: int,
    history: list[dict] | None = None,
) -> dict:
    """Prepare OpenAI API call parameters."""
    return {
        "model": model,
        "messages": build_messages(system, user_msg, history),
        "max_completion_tokens": tokens,
    }


@cached_response(ttl=DEFAULT_CACHE_TTL)
@deduplicated_request()
async def _fetch_openai_response(
    request: AIRequest,
    conversation_summary: list[dict],
    openai_client,
    config: OpenAIConfig,
) -> str | None:
    """Fetch an OpenAI response (cached/deduped) without side effects."""
    try:
        async with api_call("openai", request.logger, request) as ctx:
            api_params = _build_openai_api_params(
                config.model,
                config.system_message,
                request.message,
                config.output_tokens,
                conversation_summary,
            )

            request.logger.debug(
                "Making OpenAI API call with %d messages", len(api_params["messages"])
            )

            response = await retry_with_backoff(
                lambda: openai_client.chat.completions.create(**api_params),
                DEFAULT_API_RETRY_CONFIG,
                request.logger,
            )
            ctx.set_result(response)

            if not (response and hasattr(response, "choices") and response.choices):
                request.logger.error(
                    "OpenAI API returned invalid response structure: %s", response
                )
                return None

            response_content = response.choices[0].message.content
            if not response_content or not response_content.strip():
                request.logger.warning("OpenAI returned empty response content")
                return None

            response_content = response_content.strip()

            request.logger.info(
                "OpenAI response generated successfully: %d characters, finish_reason: %s",
                len(response_content),
                getattr(response.choices[0], "finish_reason", "unknown"),
            )

            return response_content
    except Exception:
        request.logger.exception("OpenAI API call failed after retries")
        return None


async def process_openai_message(
    request: AIRequest,
    conversation_summary: list[dict],
    openai_client,
    config: OpenAIConfig,
) -> str | None:
    """Process message using OpenAI API."""
    response_content = await _fetch_openai_response(
        request, conversation_summary, openai_client, config
    )

    if not response_content:
        return None

    return response_content
