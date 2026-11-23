"""Chat Completions adapter for OpenAI-compatible providers.

This adapter owns the request payload, the provider-family output-cap branch,
the bounded client-side web-tool loop, and response parsing. The public
processing function remains the cache and lifecycle wrapper around it.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

from src.config import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_INPUT_TOKENS,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_VISION_TOKEN_ESTIMATE,
)
from src.error_handling import (
    DEFAULT_API_RETRY_CONFIG,
    get_circuit_breaker,
    retry_with_backoff,
)
from src.image_attachments import ImagePayload
from src.message_builder import (
    build_messages,
    estimate_text_tokens,
    resolve_completion_budget,
)
from src.models import OpenAIConfig
from src.web_tools import WEB_TOOLS, should_offer_web_tools

from .base import CompletionRequest, ProbeResult, ProviderResult

openai_circuit_breaker = get_circuit_breaker("openai")

MAX_WEB_TOOL_ROUNDS = 4
MAX_TOOL_CALLS_PER_ROUND = 3
MAX_TOOL_OUTPUT_TOKENS = 12000
_TOOL_CALL_LIMIT_RESULT = '{"error":"tool-call limit reached"}'
_TOOL_BUDGET_REACHED_RESULT = '{"error":"tool-output budget reached"}'
_DEFAULT_PROBE_TIMEOUT = 10.0

ToolExecutor = Callable[..., Awaitable[str]]


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


def _provider_family(base_url: str) -> str:
    """Return the provider family implied by ``base_url``."""
    host = (urlparse(base_url).hostname or "").lower()
    if host == "ollama.com" or host.endswith(".ollama.com"):
        return "ollama"
    if host in {"localhost", "127.0.0.1"}:
        return "ollama"
    return "openai"


def _output_cap_key(base_url: str) -> str:
    """Return the output-cap parameter name for a provider family."""
    return "max_tokens" if _provider_family(base_url) == "ollama" else "max_completion_tokens"


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
    images: Sequence[ImagePayload] | None = None,
    vision_token_estimate: int = DEFAULT_VISION_TOKEN_ESTIMATE,
) -> dict:
    """Prepare OpenAI-compatible chat-completion parameters."""
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
            images=images,
            vision_token_estimate=vision_token_estimate,
        ),
    }
    budget = resolve_completion_budget(completion_tokens, context_window, input_tokens)
    params[_output_cap_key(base_url)] = budget
    if reasoning_effort:
        params["reasoning_effort"] = reasoning_effort
    return params


class ChatCompletionsProvider:
    """Adapter for an ``AsyncOpenAI``-compatible chat-completions client.

    Args:
        client: SDK client, or a test double exposing ``chat.completions.create``.
        config: OpenAI-compatible model and budget configuration.
        logger: Logger for request and tool-loop diagnostics.
        tool_executor: Optional callable used to run one model-requested tool
            call. Production passes the module-level executor so the existing
            web-tool logging and monkeypatch seam stay intact.
        probe_timeout: Maximum seconds for one ``models.list`` probe.
    """

    name = "openai"

    def __init__(
        self,
        client: Any,
        config: OpenAIConfig | None = None,
        *,
        logger: logging.Logger | None = None,
        tool_executor: ToolExecutor | None = None,
        probe_timeout: float = _DEFAULT_PROBE_TIMEOUT,
    ) -> None:
        """Store the provider client and its request policy."""
        self._client = client
        self._config = config or OpenAIConfig()
        self._logger = logger or logging.getLogger(__name__)
        self._tool_executor = tool_executor
        self._probe_timeout = probe_timeout
        self._base_url = str(getattr(client, "base_url", ""))
        self._api_key = getattr(client, "api_key", "")
        if not isinstance(self._api_key, str):
            self._api_key = ""
        self.supports_web_tools = bool(
            self._config.web_tools
            and _provider_family(self._base_url) == "ollama"
            and should_offer_web_tools(self._base_url)
        )

    @property
    def base_url(self) -> str:
        """Return the configured provider base URL."""
        return self._base_url

    def build_request(  # noqa: PLR0913 - mirrors the shared message builder
        self,
        system: str,
        user_msg: str,
        history: list[dict] | None,
        tokens: int,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        context_window: int | None = None,
        reasoning_effort: str | None = None,
        logger: logging.Logger | None = None,
        images: Sequence[ImagePayload] | None = None,
    ) -> CompletionRequest:
        """Build one normalised request using the adapter's provider policy."""
        config = self._config
        params = _build_openai_api_params(
            config.model,
            system,
            user_msg,
            tokens,
            history,
            input_tokens=config.input_tokens if input_tokens is None else input_tokens,
            output_tokens=config.output_tokens if output_tokens is None else output_tokens,
            context_window=(config.context_window if context_window is None else context_window),
            reasoning_effort=(
                config.reasoning_effort if reasoning_effort is None else reasoning_effort
            ),
            base_url=self._base_url,
            logger=logger or self._logger,
            images=images,
            vision_token_estimate=config.vision_token_estimate,
        )
        token_key = _output_cap_key(self._base_url)
        return CompletionRequest(
            model=params["model"],
            messages=params["messages"],
            max_output_tokens=int(params[token_key]),
            reasoning_effort=params.get("reasoning_effort"),
            tools=tuple(WEB_TOOLS) if self.supports_web_tools else (),
        )

    def _api_params(self, req: CompletionRequest) -> dict[str, Any]:
        """Convert a normalised request back into SDK call parameters."""
        token_key = _output_cap_key(self._base_url)
        params: dict[str, Any] = {
            "model": req.model,
            "messages": list(req.messages),
            token_key: req.max_output_tokens,
        }
        if req.reasoning_effort:
            params["reasoning_effort"] = req.reasoning_effort
        if req.tools and self.supports_web_tools:
            params["tools"] = list(req.tools)
        return params

    async def _execute_tool(self, call: dict[str, Any]) -> str:
        """Run one tool call through the injected or legacy executor."""
        executor = self._tool_executor
        if executor is None:
            from src.openai_processing import _execute_web_tool_call  # noqa: PLC0415

            executor = _execute_web_tool_call
        return await executor(
            call,
            api_key=self._api_key,
            base_url=self._base_url,
            logger=self._logger,
        )

    async def _tool_result(
        self,
        call: dict[str, Any],
        index: int,
        tool_output_tokens: int,
    ) -> tuple[str, int]:
        """Execute one tool call within the per-round and total output caps."""
        if index >= MAX_TOOL_CALLS_PER_ROUND:
            return _TOOL_CALL_LIMIT_RESULT, tool_output_tokens
        if tool_output_tokens >= MAX_TOOL_OUTPUT_TOKENS:
            return _TOOL_BUDGET_REACHED_RESULT, tool_output_tokens

        result = await self._execute_tool(call)
        result_tokens = estimate_text_tokens(result)
        if tool_output_tokens + result_tokens > MAX_TOOL_OUTPUT_TOKENS:
            return _TOOL_BUDGET_REACHED_RESULT, tool_output_tokens
        return result, tool_output_tokens + result_tokens

    async def complete(self, req: CompletionRequest) -> ProviderResult:
        """Return one parsed chat answer, resolving the bounded tool loop.

        Raises:
            ValueError: If the provider returns no choices at all.
        """
        api_params = self._api_params(req)
        messages = api_params["messages"]
        tools_enabled = bool(req.tools) and self.supports_web_tools
        final_round = MAX_WEB_TOOL_ROUNDS - 1
        tool_output_tokens = 0

        self._logger.debug("Making OpenAI API call with %d messages", len(messages))

        final_response = None
        response = None
        for round_index in range(MAX_WEB_TOOL_ROUNDS):
            round_params = api_params
            if round_index == final_round and "tools" in api_params:
                # The last round must answer; offering tools again would let
                # the model ask for results this loop can no longer use.
                round_params = {key: value for key, value in api_params.items() if key != "tools"}
            response = await openai_circuit_breaker.call(
                retry_with_backoff,
                lambda params=round_params: self._client.chat.completions.create(**params),
                DEFAULT_API_RETRY_CONFIG,
                self._logger,
            )

            if not (response and hasattr(response, "choices") and response.choices):
                self._logger.error("OpenAI API returned invalid response structure: %s", response)
                msg = "OpenAI response contained no choices"
                raise ValueError(msg)

            choice = response.choices[0]
            tool_calls = getattr(choice.message, "tool_calls", None)
            wants_tools = (
                tools_enabled
                and round_index < final_round
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
            for index, call in enumerate(calls):
                result, tool_output_tokens = await self._tool_result(
                    call,
                    index,
                    tool_output_tokens,
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

        if not (final_response and hasattr(final_response, "choices") and final_response.choices):
            self._logger.error(
                "OpenAI API returned invalid response structure: %s", final_response
            )
            msg = "OpenAI response contained no choices"
            raise ValueError(msg)

        choice = final_response.choices[0]
        response_content = choice.message.content
        finish_reason = getattr(choice, "finish_reason", None)
        if not response_content or not response_content.strip():
            return ProviderResult(
                text="",
                citations={},
                finish_reason=finish_reason,
                raw=final_response,
            )

        return ProviderResult(
            text=response_content.strip(),
            citations={},
            finish_reason=finish_reason,
            raw=final_response,
        )

    async def probe(self) -> ProbeResult:
        """List models with a bounded timeout and report reachability."""
        started_at = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._client.models.list(),
                timeout=self._probe_timeout,
            )
        except Exception as exc:  # noqa: BLE001 - probes report, never raise
            latency_ms = (time.monotonic() - started_at) * 1000
            return ProbeResult(
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                latency_ms=round(latency_ms, 1),
            )

        latency_ms = (time.monotonic() - started_at) * 1000
        model_ids = [
            model_id
            for item in getattr(response, "data", [])
            if (model_id := getattr(item, "id", None))
        ]
        if not model_ids:
            return ProbeResult(
                ok=False,
                detail="provider returned no models",
                latency_ms=round(latency_ms, 1),
            )
        return ProbeResult(
            ok=True,
            detail=f"{len(model_ids)} models available",
            latency_ms=round(latency_ms, 1),
        )
