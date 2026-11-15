"""OpenAI-compatible chat API processing and lifecycle wrappers.

The request payload, provider-family branch, tool loop, and response parsing
live in :class:`src.providers.openai_chat.ChatCompletionsProvider`. This module
keeps the public processing function, the cache/dedup decorators, and the
web-tool executor that owns the existing logging and monkeypatch seam.
"""

import json
from typing import Any

from .api_context import api_call
from .caching import cached_response, deduplicated_request
from .config import DEFAULT_CACHE_TTL
from .error_handling import retry_with_backoff
from .models import AIRequest, OpenAIConfig
from .providers.openai_chat import (
    _WEB_TOOL_BAD_ARGUMENTS,
    MAX_WEB_TOOL_ROUNDS,
    ChatCompletionsProvider,
    _build_openai_api_params,
    _object_field,
    _provider_family,
    _tool_call_payload,
    _tool_result_ok,
)
from .web_tools import call_web_tool

__all__ = [
    "MAX_WEB_TOOL_ROUNDS",
    "_WEB_TOOL_BAD_ARGUMENTS",
    "_build_openai_api_params",
    "_execute_web_tool_call",
    "_object_field",
    "_provider_family",
    "_tool_call_payload",
    "_tool_result_ok",
    "process_openai_message",
    "retry_with_backoff",
]


async def _execute_web_tool_call(
    call: dict[str, Any],
    *,
    api_key: str,
    base_url: str,
    logger: Any,
) -> str:
    """Run one model-requested tool call and return the content for the model."""
    function = call.get("function", {})
    name = str(function.get("name") or "")
    arguments = function.get("arguments") or "{}"
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    logger.debug("web_tool=%s arguments_bytes=%d", name, len(arguments))

    try:
        json.loads(arguments)
    except (TypeError, ValueError):
        logger.info("web_tool=%s ok=false", name)
        return _WEB_TOOL_BAD_ARGUMENTS

    result = await call_web_tool(
        name,
        arguments,
        api_key=api_key,
        base_url=base_url,
    )
    logger.info("web_tool=%s ok=%s", name, "true" if _tool_result_ok(result) else "false")
    return result


# Tool-using answers are cached like any other answer; the cache key stays the
# same because tool invocations are not part of the request arguments.
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
            provider = ChatCompletionsProvider(
                openai_client,
                config,
                logger=request.logger,
                tool_executor=_execute_web_tool_call,
            )
            completion_request = provider.build_request(
                config.system_message,
                request.message,
                conversation_summary,
                config.output_tokens,
                input_tokens=config.input_tokens,
                output_tokens=config.output_tokens,
                context_window=config.context_window,
                reasoning_effort=config.reasoning_effort,
                logger=request.logger,
                images=request.images,
            )
            result = await provider.complete(completion_request)
            ctx.set_result(result.raw)

            if not result.text:
                request.logger.warning(
                    "OpenAI returned empty response content (finish_reason=%s)",
                    result.finish_reason if result.finish_reason is not None else "unknown",
                )
                return None

            request.logger.info(
                "OpenAI response generated successfully: %d characters, finish_reason: %s",
                len(result.text),
                result.finish_reason if result.finish_reason is not None else "unknown",
            )

            return result.text
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
