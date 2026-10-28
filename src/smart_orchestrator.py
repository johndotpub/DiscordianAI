"""Smart AI Orchestrator - Production-Grade Clean Architecture.

This module intelligently decides which AI service to use for each message
and orchestrates the response generation with comprehensive error handling,
logging, and thread-safe conversation management.
"""

import logging
import re
from typing import Any

from .config import (
    COMPILED_CONVERSATIONAL_PATTERNS,
    COMPILED_ENTITY_PATTERNS,
    COMPILED_FACTUAL_PATTERNS,
    COMPILED_FOLLOW_UP_PATTERNS,
    COMPILED_OPENAI_WEB_INABILITY_PATTERNS,
    COMPILED_SEARCH_INTENT_PATTERNS,
    COMPILED_TIME_SENSITIVITY_PATTERNS,
    COMPILED_URL_DETECTION_PATTERNS,
    DISCORD_MARKUP_PATTERN,
    get_error_messages,
)
from .conversation_manager import ThreadSafeConversationManager
from .error_handling import get_circuit_breaker
from .models import AIClients, AIConfig, AIRequest
from .openai_processing import process_openai_message
from .perplexity_processing import process_perplexity_message

# Get centralized error messages
ERROR_MESSAGES = get_error_messages()

# Constants for magic values
DEFAULT_LOOKBACK = 6
_EARLY_WEB_INABILITY_WINDOW = 300
_QUOTED_SPAN_PATTERN = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`')
_NARRATIVE_MARKERS_PATTERN = re.compile(
    r"\b(poem|story|verse|tale|fiction|imagine|imagined|imagination|dream|"
    r"dreamed|dreamt|pretend|narrator|character|once upon a time)\b",
    re.IGNORECASE,
)


def _record_conversation_turn(
    request: AIRequest,
    response_text: str,
    ai_service: str,
    model: str,
) -> None:
    """Record the user prompt and assistant response in conversation history."""
    if not (request.message or "").strip() or not (response_text or "").strip():
        request.logger.warning("Skipping incomplete conversation turn")
        return

    conversation_key = getattr(request, "conversation_key", None)
    if conversation_key is None:
        conversation_key = request.user.id

    request.conversation_manager.add_message(conversation_key, "user", request.message)
    request.conversation_manager.add_message(
        conversation_key,
        "assistant",
        response_text,
        metadata={"ai_service": ai_service, "model": model},
    )


def _sanitize_for_routing(message: str) -> str:
    """Strip Discord markup that can trigger false-positive pattern matches.

    Produces a **throwaway copy** used exclusively by ``should_use_web_search()``.
    The original ``request.message`` is never modified — APIs, conversation
    history, cache keys, deduplication hashes, and log output all continue
    to receive the unaltered text.

    Stripped markup:
        - Custom / animated emojis: ``<a?:name:id>``
        - User mentions: ``<@id>`` or ``<@!id>``
        - Role mentions: ``<@&id>``
        - Channel mentions: ``<#id>``
        - Timestamps: ``<t:epoch>`` / ``<t:epoch:style>``

    Args:
        message: Raw Discord message text.

    Returns:
        Message with Discord markup tokens removed and excess whitespace
        collapsed.
    """
    cleaned = DISCORD_MARKUP_PATTERN.sub("", message)
    # Collapse runs of whitespace left behind by removed tokens.
    return " ".join(cleaned.split()).strip()


def has_time_sensitivity(message: str) -> bool:
    """Check if message implies current/recent information is needed."""
    return any(pattern.search(message) for pattern in COMPILED_TIME_SENSITIVITY_PATTERNS)


def _query_requires_live_data(message: str) -> bool:
    """Return True when a query plausibly needs current or web-sourced data."""
    if not message:
        return False
    return (
        any(p.search(message) for p in COMPILED_URL_DETECTION_PATTERNS)
        or any(p.search(message) for p in COMPILED_SEARCH_INTENT_PATTERNS)
        or has_time_sensitivity(message)
    )


def _is_quoted_text(response_text: str, position: int) -> bool:
    """Return True when a position falls inside quotes, code, or a blockquote."""
    quoted = _QUOTED_SPAN_PATTERN.finditer(response_text)
    if any(match.start() <= position < match.end() for match in quoted):
        return True

    line_start = response_text.rfind("\n", 0, position) + 1
    line_end = response_text.find("\n", position)
    if line_end == -1:
        line_end = len(response_text)
    if response_text[line_start:line_end].lstrip().startswith(">"):
        return True

    return response_text.count("```", 0, position) % 2 == 1


def _is_narrative_context(response_text: str, position: int) -> bool:
    """Return True when the phrase sits inside creative or quoted narrative."""
    sentence_start = (
        max(
            response_text.rfind(".", 0, position),
            response_text.rfind("!", 0, position),
            response_text.rfind("?", 0, position),
            response_text.rfind("\n", 0, position),
        )
        + 1
    )
    endings = [
        index
        for index in (
            response_text.find(".", position),
            response_text.find("!", position),
            response_text.find("?", position),
            response_text.find("\n", position),
        )
        if index != -1
    ]
    sentence_end = min(endings) + 1 if endings else len(response_text)
    context = response_text[max(0, sentence_start - 120) : sentence_end]
    return bool(_NARRATIVE_MARKERS_PATTERN.search(context))


def _detect_openai_web_inability(
    response_text: str,
    query: str | None = None,
) -> bool:
    """Detect a genuine early web-inability admission in an OpenAI response.

    The phrase must be near the start of the response and outside quoted or
    narrative text. When a query is supplied, it must also plausibly need live
    data; otherwise a creative answer that merely mentions the internet is kept.

    Args:
        response_text: The assistant's response text from OpenAI.
        query: Optional original user query used to check live-data intent.

    Returns:
        True if a reroute to Perplexity is recommended, False otherwise.
    """
    if not response_text:
        return False
    if query is not None and not _query_requires_live_data(query):
        return False

    for pattern in COMPILED_OPENAI_WEB_INABILITY_PATTERNS:
        for match in pattern.finditer(response_text):
            if match.start() > _EARLY_WEB_INABILITY_WINDOW:
                continue
            if _is_quoted_text(response_text, match.start()):
                continue
            if _is_narrative_context(response_text, match.start()):
                continue
            return True
    return False


def is_factual_query(message: str) -> bool:
    """Check if message is asking for factual information."""
    return any(pattern.search(message) for pattern in COMPILED_FACTUAL_PATTERNS)


def is_conversational_or_creative(message: str) -> bool:
    """Check if message is conversational, creative, or personal."""
    return any(pattern.search(message) for pattern in COMPILED_CONVERSATIONAL_PATTERNS)


def should_use_web_search(
    message: str,
    conversation_manager: ThreadSafeConversationManager | None = None,
    user_id: int | None = None,
    lookback_messages: int = DEFAULT_LOOKBACK,
    conversation_key: str | None = None,
) -> bool:
    """Intelligently determine if a message needs a web-enabled model.

    Uses a series of heuristics (URLs, explicit search intent, conversational
    context consistency, time-sensitivity, factual queries, and entity
    detection) to decide whether a query should be routed to a web-enabled
    model such as Perplexity.

    Args:
        message: The raw message text to evaluate.
        conversation_manager: Optional `ThreadSafeConversationManager` used
            to consult recent AI service usage for consistency-based routing.
        user_id: Optional user id used with `conversation_manager` when no
            conversation key is available.
        lookback_messages: How many recent messages to inspect for
            consistency checks.
        conversation_key: Optional DM/channel conversation key used to look up
            recent service usage in the correct conversation.

    Returns:
        True if the message should be routed to a web-enabled model,
        otherwise False.
    """
    logger = logging.getLogger(__name__)
    # Emit trigger-identifying log lines for telemetry and debugging. We keep
    # this at DEBUG level because routing decisions are verbose and mostly
    # useful during troubleshooting.
    # _identify_routing_triggers is cheap; guard defensively but avoid
    # catching broad exceptions. If it fails, fall back to an empty list.
    try:
        triggers = _identify_routing_triggers(
            message,
            conversation_manager,
            user_id,
            lookback_messages,
            conversation_key,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback  # noqa: BLE001
        logger.debug("should_use_web_search: trigger identification failed: %s", exc)
        triggers = []
    logger.debug("should_use_web_search: message=%s triggers=%s", message, triggers)
    # PRIORITY CHECK: If message contains URLs, always use web search
    if any(pattern.search(message) for pattern in COMPILED_URL_DETECTION_PATTERNS):
        return True

    # PRIORITY CHECK: Explicit user intent to search/look-up
    if any(p.search(message) for p in COMPILED_SEARCH_INTENT_PATTERNS):
        return True

    # Check conversation context. A follow-up only inherits the previous
    # service when there is a real prior turn in this same conversation.
    scope_key = conversation_key if conversation_key is not None else user_id
    if any(pattern.search(message) for pattern in COMPILED_FOLLOW_UP_PATTERNS):
        recent_ai_service = None
        if conversation_manager and scope_key:
            recent_ai_service = conversation_manager.get_recent_ai_service(
                scope_key,
                lookback_messages=lookback_messages,
            )
        if recent_ai_service:
            return recent_ai_service == "perplexity"
        return False

    # If it's clearly conversational or creative, don't use web search
    if is_conversational_or_creative(message):
        return False

    # Positive indicators for web search
    return (
        has_time_sensitivity(message)
        or is_factual_query(message)
        or any(p.search(message) for p in COMPILED_ENTITY_PATTERNS)
    )


def _identify_routing_triggers(
    message: str,
    conversation_manager: ThreadSafeConversationManager | None = None,
    user_id: int | None = None,
    lookback_messages: int = DEFAULT_LOOKBACK,
    conversation_key: str | None = None,
) -> list[str]:
    """Return human-readable list of routing trigger reasons for telemetry.

    This helper checks the same heuristics used by `should_use_web_search`
    and returns short labels describing why a message would (or would not)
    be routed to a web-enabled model. It's intended for logging/telemetry
    and must be cheap to compute.
    """
    triggers: list[str] = []
    scope_key = conversation_key if conversation_key is not None else user_id

    if any(p.search(message) for p in COMPILED_URL_DETECTION_PATTERNS):
        triggers.append("url")

    if any(p.search(message) for p in COMPILED_SEARCH_INTENT_PATTERNS):
        triggers.append("search_intent")

    if (
        conversation_manager
        and scope_key
        and any(p.search(message) for p in COMPILED_FOLLOW_UP_PATTERNS)
    ):
        recent = conversation_manager.get_recent_ai_service(scope_key, lookback_messages)
        if recent:
            triggers.append(f"consistency:{recent}")

    if any(p.search(message) for p in COMPILED_CONVERSATIONAL_PATTERNS):
        triggers.append("conversational")

    if any(p.search(message) for p in COMPILED_TIME_SENSITIVITY_PATTERNS):
        triggers.append("time_sensitivity")

    if any(p.search(message) for p in COMPILED_FACTUAL_PATTERNS):
        triggers.append("factual")

    for p in COMPILED_ENTITY_PATTERNS:
        m = p.search(message)
        if m:
            triggers.append(f"entity:{m.group(0)}")
            break

    return triggers


async def _process_perplexity_only_mode(
    request: AIRequest,
    perplexity_client: Any,
    config: AIConfig,
    conversation_summary: list[dict] | None = None,
) -> tuple[str, bool, dict | None]:
    """Process message using Perplexity-only mode."""
    request.logger.info("Running in Perplexity-only mode")
    try:
        result = await process_perplexity_message(
            request, perplexity_client, config.perplexity, conversation_summary
        )
        if result:
            res_content, suppress, embed = result
            _record_conversation_turn(request, res_content, "perplexity", config.perplexity.model)
            request.logger.info("Perplexity success (%d chars)", len(res_content))
            return res_content, suppress, embed

        request.logger.error("Perplexity returned no response")
        return ERROR_MESSAGES["no_response_generated"], False, None
    except Exception:
        request.logger.exception("Perplexity processing failed")
        return ERROR_MESSAGES["web_search_unavailable"], False, None


async def _process_openai_only_mode(
    request: AIRequest,
    conversation_summary: list[dict],
    openai_client: Any,
    config: AIConfig,
) -> tuple[str, bool, dict | None]:
    """Process message using OpenAI-only mode."""
    request.logger.info("Running in OpenAI-only mode")
    try:
        response_content = await process_openai_message(
            request, conversation_summary, openai_client, config.openai
        )
        if response_content:
            _record_conversation_turn(request, response_content, "openai", config.openai.model)
            request.logger.info("OpenAI success (%d chars)", len(response_content))
            return response_content, False, None

        request.logger.error("OpenAI returned no response")
        if get_circuit_breaker("openai").state == "OPEN":
            return ERROR_MESSAGES["ai_service_unavailable"], False, None
        return ERROR_MESSAGES["no_response_generated"], False, None
    except Exception:
        request.logger.exception("OpenAI processing failed")
        return ERROR_MESSAGES["ai_service_unavailable"], False, None


async def get_smart_response(
    request: AIRequest,
    conversation_summary: list[dict],
    clients: AIClients,
    config: AIConfig,
    orchestrator_config: dict | None = None,
) -> tuple[str, bool, dict | None]:
    """Choose the best AI service and generate a response.

    This is the main orchestrator entrypoint. It inspects available AI
    clients and routes the request to Perplexity, OpenAI, or a hybrid
    strategy depending on configuration and heuristics. The function
    handles error conditions and returns a degraded fallback when
    appropriate.

    Args:
        request: An `AIRequest` containing message, user, logger and
            conversation manager.
        conversation_summary: List of messages summarizing recent context
            to pass to models (already formatted for the client API).
        clients: `AIClients` containing available OpenAI/Perplexity clients.
        config: `AIConfig` with service-specific configuration.
        orchestrator_config: Optional dictionary of orchestrator tuning
            values (e.g., lookback window overrides).

    Returns:
        A tuple of `(response_text, suppress_embeds, embed_metadata)` where
        `suppress_embeds` indicates whether to suppress embed rendering and
        `embed_metadata` contains structured citation/embed information or
        `None` when not applicable.

    Raises:
        All exceptions are caught and translated into an error message
        tuple; the function will not raise under normal operation.
    """
    try:
        request.logger.info("Orchestrating response for user %s", request.user.id)

        # Mode 1: Perplexity only
        if clients.perplexity and not clients.openai:
            return await _process_perplexity_only_mode(
                request, clients.perplexity, config, conversation_summary
            )

        # Mode 2: OpenAI only
        if clients.openai and not clients.perplexity:
            return await _process_openai_only_mode(
                request, conversation_summary, clients.openai, config
            )

        # Mode 3: Hybrid mode
        if clients.openai and clients.perplexity:
            return await _process_hybrid_mode(
                request, conversation_summary, clients, config, orchestrator_config
            )

        request.logger.critical("No AI clients available")
        return ERROR_MESSAGES["configuration_error"], False, None

    except Exception:
        request.logger.exception("Unexpected error in smart orchestrator")
        return ERROR_MESSAGES["unexpected_error"], False, None


async def _process_hybrid_mode(
    request: AIRequest,
    conversation_summary: list[dict],
    clients: AIClients,
    config: AIConfig,
    orchestrator_config: dict | None = None,
) -> tuple[str, bool, dict | None]:
    """Handle hybrid routing between OpenAI and Perplexity."""
    lookback = DEFAULT_LOOKBACK
    if orchestrator_config:
        lookback = orchestrator_config.get("LOOKBACK_MESSAGES_FOR_CONSISTENCY", DEFAULT_LOOKBACK)

    sanitized = _sanitize_for_routing(request.message)
    conversation_key = getattr(request, "conversation_key", None)
    needs_web = should_use_web_search(
        sanitized,
        request.conversation_manager,
        request.user.id,
        lookback_messages=lookback,
        conversation_key=conversation_key,
    )

    # Routing telemetry: identify and log the reasons that influenced routing
    triggers = _identify_routing_triggers(
        sanitized,
        request.conversation_manager,
        request.user.id,
        lookback,
        conversation_key,
    )
    request.logger.info(
        "Routing decision: needs_web=%s; triggers=%s; sanitized=%s",
        needs_web,
        triggers,
        sanitized,
    )

    if needs_web:
        request.logger.info("Routing to Perplexity")
        res = await process_perplexity_message(
            request, clients.perplexity, config.perplexity, conversation_summary
        )
        if res:
            res_content, suppress, embed = res
            _record_conversation_turn(request, res_content, "perplexity", config.perplexity.model)
            return res_content, suppress, embed
        request.logger.warning("Perplexity failed, falling back to OpenAI")

    request.logger.info("Routing to OpenAI")
    res_content = await process_openai_message(
        request, conversation_summary, clients.openai, config.openai
    )
    if res_content:
        # If OpenAI explicitly says it cannot browse/look up current web data,
        # detect that and reroute to Perplexity (persona-agnostic detection).
        if _detect_openai_web_inability(res_content, request.message):
            request.logger.debug(
                "Discarding OpenAI answer after web-inability reroute: %s",
                res_content,
            )
            request.logger.warning(
                "OpenAI response indicates web-inability; rerouting to Perplexity"
            )
            per_res = await process_perplexity_message(
                request,
                clients.perplexity,
                config.perplexity,
                conversation_summary,
            )
            if per_res:
                per_text, per_suppress, per_embed = per_res
                _record_conversation_turn(request, per_text, "perplexity", config.perplexity.model)
                return per_text, per_suppress, per_embed
            # Degraded fallback: return original OpenAI response if Perplexity also fails
            request.logger.warning(
                "Perplexity failed after OpenAI reroute; returning original "
                "OpenAI response as degraded fallback"
            )
            _record_conversation_turn(request, res_content, "openai", config.openai.model)
            return res_content, False, None
        _record_conversation_turn(request, res_content, "openai", config.openai.model)
        return res_content, False, None

    # If OpenAI returned no response (None/empty), attempt Perplexity as a fallback
    request.logger.info("OpenAI returned no response; attempting Perplexity fallback")
    per_res = await process_perplexity_message(
        request, clients.perplexity, config.perplexity, conversation_summary
    )
    if per_res:
        per_text, per_suppress, per_embed = per_res
        _record_conversation_turn(request, per_text, "perplexity", config.perplexity.model)
        return per_text, per_suppress, per_embed

    request.logger.error("Both services failed or returned no response")
    return ERROR_MESSAGES["both_services_unavailable"], False, None
