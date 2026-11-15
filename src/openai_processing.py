"""OpenAI-compatible chat API processing with thread-safe error handling.

This module handles all chat API interactions (Ollama Cloud by default, OpenAI
optionally), conversation state management, and error recovery.
"""

import json
from typing import Any
from urllib.parse import urlparse

from .api_context import api_call
from .caching import cached_response, deduplicated_request
from .config import (
    DEFAULT_CACHE_TTL,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_INPUT_TOKENS,
    DEFAULT_REASONING_EFFORT,
)
from .error_handling import (
    DEFAULT_API_RETRY_CONFIG,
    get_circuit_breaker,
    retry_with_backoff,
)
from .message_builder import build_messages, resolve_completion_budget
from .models import AIRequest, OpenAIConfig
from .web_tools import WEB_TOOLS, call_web_tool, should_offer_web_tools

openai_circuit_breaker = get_circuit_breaker("openai")

MAX_WEB_TOOL_ROUNDS = 4
_WEB_TOOL_BAD_ARGUMENTS = '{"error":"bad arguments"}'


def _object_field(value: Any, name: str, default: Any = None) -> Any:
    """Read a field from an SDK object or a plain mapping."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _tool_call_payload(tool_call: Any) -> dict[str, Any]:
    """Convert an SDK tool call into a chat-completions message payload."""
    function = _object_field(tool_call, "function")
    return {
        "id": _object_field(tool_call, "id", ""),
        "type": _object_field(tool_call, "type", "function") or "function",
        "function": {
            "name": _object_field(function, "name", ""),
            "arguments": _object_field(function, "arguments", "{}") or "{}",
        },
    }


def _tool_result_ok(result: str) -> bool:
    """Return whether a tool result is free of the error envelope."""
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return True
    return not (isinstance(payload, dict) and "error" in payload)


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
    logger.debug("web_tool=%s arguments=%s", name, arguments)

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


def _provider_family(base_url: str) -> str:
    """Return the provider family implied by ``base_url``."""
    host = (urlparse(base_url).hostname or "").lower()
    if host == "ollama.com" or host.endswith(".ollama.com"):
        return "ollama"
    if host in {"localhost", "127.0.0.1"}:
        return "ollama"
    return "openai"


def _build_openai_api_params(  # noqa: PLR0913
    model: str,
    system: str,
    user_msg: str,
    tokens: int,
    history: list[dict] | None = None,
    *,
    input_tokens: int = DEFAULT_INPUT_TOKENS,
    output_tokens: int | None = None,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    base_url: str = "",
    logger=None,
) -> dict:
    """Prepare OpenAI API call parameters."""
    completion_tokens = tokens if output_tokens is None else output_tokens
    params = {
        "model": model,
        "messages": build_messages(
            system,
            user_msg,
            history,
            input_tokens=input_tokens,
            output_tokens=completion_tokens,
            context_window=context_window,
            logger=logger,
        ),
    }
    budget = resolve_completion_budget(completion_tokens, context_window, input_tokens)
    if _provider_family(base_url) == "ollama":
        params["max_tokens"] = budget
    else:
        params["max_completion_tokens"] = budget
    if reasoning_effort:
        params["reasoning_effort"] = reasoning_effort
    return params


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
            base_url = str(getattr(openai_client, "base_url", ""))
            api_params = _build_openai_api_params(
                config.model,
                config.system_message,
                request.message,
                config.output_tokens,
                conversation_summary,
                input_tokens=config.input_tokens,
                output_tokens=config.output_tokens,
                context_window=config.context_window,
                reasoning_effort=config.reasoning_effort,
                base_url=base_url,
                logger=request.logger,
            )

            tools_enabled = (
                getattr(config, "web_tools", True)
                and _provider_family(base_url) == "ollama"
                and should_offer_web_tools(base_url)
            )
            if tools_enabled:
                api_params["tools"] = WEB_TOOLS

            messages = api_params["messages"]
            api_key = getattr(openai_client, "api_key", "")
            if not isinstance(api_key, str):
                api_key = ""

            request.logger.debug("Making OpenAI API call with %d messages", len(messages))

            final_response = None
            response = None
            for _round in range(MAX_WEB_TOOL_ROUNDS):
                response = await openai_circuit_breaker.call(
                    retry_with_backoff,
                    lambda: openai_client.chat.completions.create(**api_params),
                    DEFAULT_API_RETRY_CONFIG,
                    request.logger,
                )

                if not (response and hasattr(response, "choices") and response.choices):
                    request.logger.error(
                        "OpenAI API returned invalid response structure: %s", response
                    )
                    return None

                choice = response.choices[0]
                tool_calls = getattr(choice.message, "tool_calls", None)
                wants_tools = (
                    tools_enabled
                    and getattr(choice, "finish_reason", None) == "tool_calls"
                    and bool(tool_calls)
                )
                if not wants_tools:
                    final_response = response
                    break

                calls = [_tool_call_payload(tool_call) for tool_call in tool_calls]
                messages.append(
                    {
                        "role": "assistant",
                        "content": getattr(choice.message, "content", None) or "",
                        "tool_calls": calls,
                    }
                )
                for call in calls:
                    result = await _execute_web_tool_call(
                        call,
                        api_key=api_key,
                        base_url=base_url,
                        logger=request.logger,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": result,
                        }
                    )
            else:
                final_response = response

            ctx.set_result(final_response)

            if not (
                final_response and hasattr(final_response, "choices") and final_response.choices
            ):
                request.logger.error(
                    "OpenAI API returned invalid response structure: %s", final_response
                )
                return None

            response_content = final_response.choices[0].message.content
            if not response_content or not response_content.strip():
                request.logger.warning(
                    "OpenAI returned empty response content (finish_reason=%s)",
                    getattr(final_response.choices[0], "finish_reason", "unknown"),
                )
                return None

            response_content = response_content.strip()

            request.logger.info(
                "OpenAI response generated successfully: %d characters, finish_reason: %s",
                len(response_content),
                getattr(final_response.choices[0], "finish_reason", "unknown"),
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
