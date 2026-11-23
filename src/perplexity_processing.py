"""Perplexity Agent API processing and Discord citation formatting.

The request shape, provider call, and citation extraction live in
:class:`src.providers.perplexity.AgentResponsesProvider`. This module keeps the
public processing function, cache policy, Discord formatting, and the
compatibility exports used by callers and tests.
"""

import hashlib
import json
import re
from typing import Any

from .api_context import api_call
from .caching import cached_response
from .citation_formatting import _format_unlinked_citations, format_citations
from .config import DEFAULT_CACHE_TTL
from .discord_embeds import citation_embed_formatter
from .error_handling import ProviderCallError, classify_error
from .message_splitter import CitationMap, sanitize_model_output, should_suppress_embeds
from .models import AIRequest, PerplexityConfig
from .providers.base import AssistantText, ProviderResult
from .providers.perplexity import (
    FETCH_URL_INSTRUCTIONS,
    WEB_TOOLS,
    AgentResponsesProvider,
    _build_api_params,
    _normalize_citation_text,
    _parse_agent_response,
    extract_citations_from_response,
)

__all__ = [
    "FETCH_URL_INSTRUCTIONS",
    "LINK_THRESHOLD",
    "WEB_TOOLS",
    "_build_api_params",
    "_clean_bare_urls_safely",
    "_normalize_citation_text",
    "_parse_agent_response",
    "extract_citations_from_response",
    "format_citations_for_discord",
    "process_perplexity_message",
]

# Constants
LINK_THRESHOLD = 2


def _history_digest(conversation_summary: list[dict] | None) -> str:
    """Hash ordered conversation history for the explicit cache key."""
    if not conversation_summary:
        payload = "[]"
    else:
        try:
            payload = json.dumps(
                conversation_summary,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        except (TypeError, ValueError):
            payload = repr(conversation_summary)
    return hashlib.sha256(payload.encode()).hexdigest()


def _scope_id(request: AIRequest) -> str | None:
    """Return the conversation key, or the requester id as a legacy fallback."""
    conversation_key = getattr(request, "conversation_key", None)
    if conversation_key is not None:
        return str(conversation_key)
    user = getattr(request, "user", None)
    user_id = getattr(user, "id", None)
    return str(user_id) if user_id is not None else None


def _routing_fields(request: AIRequest) -> tuple[bool, str, bool]:
    """Return cacheability, salt, and degraded state for a request."""
    routing = getattr(request, "routing", None)
    if routing is None:
        return True, "direct:perplexity", False
    if isinstance(routing, dict):
        return (
            bool(routing.get("cacheable", True)),
            str(routing.get("salt") or "direct:perplexity"),
            bool(routing.get("degraded", False)),
        )
    return (
        bool(getattr(routing, "cacheable", True)),
        str(getattr(routing, "salt", None) or "direct:perplexity"),
        bool(getattr(routing, "degraded", False)),
    )


def _perplexity_cache_key(
    request: AIRequest,
    perplexity_client: Any,
    config: PerplexityConfig,
    conversation_summary: list[dict] | None = None,
    **_kwargs: Any,
) -> str | None:
    """Build a fully scoped cache key for one Perplexity request."""
    cacheable, salt, degraded = _routing_fields(request)
    if not cacheable:
        return None

    scope = _scope_id(request)
    if scope is None:
        return None

    key_data = {
        "service": "perplexity",
        "message": str(request.message).strip(),
        "model": config.model,
        "system_digest": hashlib.sha256(str(config.system_message).encode()).hexdigest(),
        "scope": scope,
        "history_digest": _history_digest(conversation_summary),
        "salt": salt,
        "degraded": degraded,
        "client_base_url": str(getattr(perplexity_client, "base_url", "")),
        "function": "_fetch_perplexity_response",
    }
    return hashlib.sha256(
        json.dumps(key_data, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def _clean_bare_urls_safely(text: str, urls: list[str]) -> str:
    """Safely remove bare URLs that aren't part of markdown links."""
    url_set = set(urls)
    if not url_set:
        return text

    alternatives = "|".join(re.escape(url) for url in dict.fromkeys(urls))
    pattern = re.compile(rf"(?<!\]\()(?:{alternatives})(?!\s*\))")

    def replace_url(match) -> str:
        matched = match.group(0)
        return "" if matched in url_set else matched

    return pattern.sub(replace_url, text)


def format_citations_for_discord(
    text: str, citations: dict[str, str], *, linkify: bool = True
) -> str:
    """Format numbered citations for Discord output.

    Replaces numbered citation markers in `text` with either plain
    bracketed markers (e.g., "[1]") or markdown links depending on
    the `linkify` flag.

    Args:
        text: The response text potentially containing citation markers.
        citations: Mapping from citation numbers (strings) to URLs.
        linkify: If True, replace markers with markdown links pointing at
            the resolved URLs; otherwise leave bracketed markers.

    Returns:
        The transformed text ready for posting to Discord.
    """
    if not linkify:
        return _format_unlinked_citations(text, citations)
    return format_citations(text, citations, style="message")


def _handle_provider_result(
    result: ProviderResult,
    request: AIRequest,
) -> tuple[str, bool, dict | None] | None:
    """Format one parsed provider result for Discord."""
    if not result.text:
        request.logger.warning("Perplexity returned empty response content")
        return None

    citations = result.citations
    if not isinstance(citations, CitationMap):
        citations = CitationMap(citations)
    final_text = format_citations_for_discord(result.text, citations, linkify=False)
    final_text = sanitize_model_output(final_text, citations)
    suppress_embeds = should_suppress_embeds(final_text, threshold=LINK_THRESHOLD)
    truncated = result.finish_reason == "length"
    if truncated:
        request.logger.warning(
            "Perplexity response hit the output-token limit; delivering a partial answer"
        )

    embed_data = None
    if citations:
        embed, meta = citation_embed_formatter.create_citation_embed(final_text, citations)
        if embed.description:
            embed.description = sanitize_model_output(embed.description, citations)
        embed_data = {
            "embed": embed,
            "citations": citations,
            "clean_text": final_text,
            "meta": meta,
        }

    return AssistantText(final_text, truncated=truncated), suppress_embeds, embed_data


@cached_response(
    ttl=DEFAULT_CACHE_TTL,
    key_fn=_perplexity_cache_key,
    result_text=lambda result: result[0] if isinstance(result, tuple) and result else None,
)
async def _fetch_perplexity_response(
    request: AIRequest,
    perplexity_client: Any,
    config: PerplexityConfig,
    conversation_summary: list[dict] | None = None,
    *,
    raise_on_failure: bool = False,
) -> tuple[str, bool, dict | None] | None:
    """Fetch and format a Perplexity answer behind the shared cache."""
    try:
        async with api_call("perplexity", request.logger, request) as ctx:
            provider = AgentResponsesProvider(perplexity_client, config, logger=request.logger)
            completion_request = provider.build_request(
                config.system_message,
                request.message,
                conversation_summary,
                config.output_tokens,
                input_tokens=getattr(config, "input_tokens", None),
                output_tokens=config.output_tokens,
                context_window=getattr(config, "context_window", None),
                logger=request.logger,
            )
            result = await provider.complete(completion_request)
            ctx.set_result(result.raw)
            return _handle_provider_result(result, request)
    except Exception as exc:
        request.logger.exception("Perplexity API call failed for user %s", request.user.id)
        if raise_on_failure:
            raise ProviderCallError(classify_error(exc), provider="perplexity") from exc
        return None


async def process_perplexity_message(
    request: AIRequest,
    perplexity_client: Any,
    config: PerplexityConfig,
    conversation_summary: list[dict] | None = None,
    *,
    raise_on_failure: bool = False,
) -> tuple[str, bool, dict | None] | None:
    """Get a web-enabled response from Perplexity and format it for Discord.

    This function builds the Perplexity API parameters, calls the Perplexity
    API, extracts and formats citations. URLs in the message need no special
    handling: the Agent API's search and fetch tools open them.
    It returns `None` when the API call fails or times out.

    Args:
        request: An `AIRequest` containing message, user, logger and
            conversation manager.
        perplexity_client: The Perplexity client object used to make API calls.
        config: `PerplexityConfig` containing model and system message.
        conversation_summary: Optional prior conversation turns to send between
            the system message and the current user message.
        raise_on_failure: Raise a typed ``ProviderCallError`` instead of
            returning ``None`` when the provider call fails.

    Returns:
        A tuple `(response_text, suppress_embeds, embed_metadata)` when a
        successful response is obtained, or `None` on failure/timeouts.
    """
    return await _fetch_perplexity_response(
        request,
        perplexity_client,
        config,
        conversation_summary,
        raise_on_failure=raise_on_failure,
    )
