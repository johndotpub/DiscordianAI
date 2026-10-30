"""Smart AI Orchestrator - production routing and response orchestration.

This module asks the routing package for one evidence-based decision per
message, then calls the selected provider, handles fallback, and records the
successful turn in conversation history.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
import re
from typing import Any

from .config import (
    DEFAULT_ROUTER_WEB_THRESHOLD_ANNOUNCE,
    DEFAULT_ROUTER_WEB_THRESHOLD_CHANNEL,
    DEFAULT_ROUTER_WEB_THRESHOLD_DM,
    DISCORD_MARKUP_PATTERN,
    get_error_messages,
)
from .error_handling import get_circuit_breaker
from .models import AIClients, AIConfig, AIRequest, RoutingMetadata
from .openai_processing import process_openai_message
from .perplexity_processing import process_perplexity_message
from .routing import build_router, decision_log_fields
from .routing.context import build_router_input
from .routing.contracts import RouteDecision

# Get centralized error messages
ERROR_MESSAGES = get_error_messages()


async def _invoke_openai(request, client, service_config, summary):
    return await process_openai_message(request, summary, client, service_config)


async def _invoke_perplexity(request, client, service_config, summary):
    return await process_perplexity_message(request, client, service_config, summary)


@dataclass(frozen=True)
class _OnlyModeSpec:
    """Describe how to run one provider in single-provider mode."""

    service: str
    label: str
    config_attr: str
    invoke: Callable[..., Awaitable[Any]]
    normalize: Callable[[Any], tuple[str, bool, dict | None]]
    no_response_error: str
    exception_error: str
    breaker_error: str | None = None


_ONLY_MODE_SPECS: dict[str, _OnlyModeSpec] = {
    "perplexity": _OnlyModeSpec(
        service="perplexity",
        label="Perplexity",
        config_attr="perplexity",
        invoke=_invoke_perplexity,
        normalize=lambda result: result,
        no_response_error=ERROR_MESSAGES["no_response_generated"],
        exception_error=ERROR_MESSAGES["web_search_unavailable"],
    ),
    "openai": _OnlyModeSpec(
        service="openai",
        label="OpenAI",
        config_attr="openai",
        invoke=_invoke_openai,
        normalize=lambda result: (result, False, None),
        no_response_error=ERROR_MESSAGES["no_response_generated"],
        exception_error=ERROR_MESSAGES["ai_service_unavailable"],
        breaker_error=ERROR_MESSAGES["ai_service_unavailable"],
    ),
}

# Constants for magic values
DEFAULT_LOOKBACK = 6
_EARLY_WEB_INABILITY_WINDOW = 300
_QUOTED_SPAN_PATTERN = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`')
_NARRATIVE_MARKERS_PATTERN = re.compile(
    r"\b(poem|story|verse|tale|fiction|imagine|imagined|imagination|dream|"
    r"dreamed|dreamt|pretend|narrator|character|once upon a time)\b",
    re.IGNORECASE,
)

# Persona-agnostic phrases that admit an answer could not use live web data.
_OPENAI_WEB_INABILITY_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        (
            r"\b(can't|cannot|unable to|not able to)\s+"
            r"(browse|search|access|look up|check)\s+"
            r"(the\s+)?(web|internet|online|real.?time|current|live)\b"
        ),
        (
            r"\b(don't|do not|doesn't|does not)\s+have\s+"
            r"(access to|the ability to access)\s+"
            r"(?:the\s+)?(real.?time|current|live|external|web|internet)\b"
        ),
        (
            r"\b(no|without)\s+(access to|ability to access)\s+"
            r"(the\s+)?(internet|web|real.?time|external|current)\b"
        ),
        r"\b(knowledge|training)\s+(cutoff|cut.?off)\b",
        r"\bas of my (last|latest)\s+(update|training)\b",
        r"\b(not equipped|not designed)\s+to\s+(browse|search|access)\b",
        (
            r"\b(can't|cannot|unable to)\s+(verify|confirm|check|provide)\s+"
            r"(current|real.?time|up.?to.?date|live)\b"
        ),
        (
            r"\b(don't|do not)\s+have\s+(real.?time|current|live|up.?to.?date)\s+"
            r"(information|data|access)\b"
        ),
    )
]

_CHANNEL_THRESHOLD_KEYS = {
    "channel": "ROUTER_WEB_THRESHOLD_CHANNEL",
    "announcement": "ROUTER_WEB_THRESHOLD_ANNOUNCE",
    "dm": "ROUTER_WEB_THRESHOLD_DM",
}
_CHANNEL_THRESHOLD_DEFAULTS = {
    "channel": DEFAULT_ROUTER_WEB_THRESHOLD_CHANNEL,
    "announcement": DEFAULT_ROUTER_WEB_THRESHOLD_ANNOUNCE,
    "dm": DEFAULT_ROUTER_WEB_THRESHOLD_DM,
}


@dataclass
class AttemptLedger:
    """Track which providers were already tried during one user request."""

    providers: set[str] = field(default_factory=set)

    def record(self, provider: str) -> None:
        """Remember that ``provider`` was called, whether it succeeded or not."""
        self.providers.add(provider)

    def already_tried(self, provider: str) -> bool:
        """Return True when ``provider`` already had an attempt in this request."""
        return provider in self.providers


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

    manager = getattr(request, "conversation_manager", None)
    if manager is None:
        request.logger.warning("No conversation manager; skipping history write")
        return

    conversation_key = getattr(request, "conversation_key", None)
    if conversation_key is None:
        conversation_key = request.user.id

    manager.add_message(conversation_key, "user", request.message)
    manager.add_message(
        conversation_key,
        "assistant",
        response_text,
        metadata={"ai_service": ai_service, "model": model},
    )


def _sanitize_for_routing(message: str) -> str:
    """Strip Discord markup that can create false routing cues.

    Produces a throwaway copy used only to build a ``RouterInput``. The
    original ``request.message`` is never modified for APIs, conversation
    history, cache keys, or log output.
    """
    cleaned = DISCORD_MARKUP_PATTERN.sub("", message)
    return " ".join(cleaned.split()).strip()


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


def _detect_openai_web_inability(response_text: str) -> bool:
    """Detect a genuine early web-inability admission in an OpenAI response.

    The phrase must be near the start of the response and outside quoted or
    narrative text.

    Args:
        response_text: The assistant's response text from OpenAI.

    Returns:
        True if a reroute to Perplexity is recommended, False otherwise.
    """
    if not response_text:
        return False

    for pattern in _OPENAI_WEB_INABILITY_PATTERNS:
        for match in pattern.finditer(response_text):
            if match.start() > _EARLY_WEB_INABILITY_WINDOW:
                continue
            if _is_quoted_text(response_text, match.start()):
                continue
            if _is_narrative_context(response_text, match.start()):
                continue
            return True
    return False


def _web_threshold(orchestrator_config: dict | None, channel_kind: str) -> float:
    """Return the configured web threshold for one channel kind."""
    kind = channel_kind if channel_kind in _CHANNEL_THRESHOLD_KEYS else "channel"
    key = _CHANNEL_THRESHOLD_KEYS[kind]
    default = _CHANNEL_THRESHOLD_DEFAULTS[kind]
    if not orchestrator_config or key not in orchestrator_config:
        return default
    try:
        return float(orchestrator_config[key])
    except (TypeError, ValueError):
        return default


def _lookback(orchestrator_config: dict | None) -> int:
    """Return the configured follow-up lookback window."""
    if not orchestrator_config:
        return DEFAULT_LOOKBACK
    return orchestrator_config.get("LOOKBACK_MESSAGES_FOR_CONSISTENCY", DEFAULT_LOOKBACK)


async def _build_route_decision(
    request: AIRequest,
    orchestrator_config: dict | None,
) -> RouteDecision:
    """Build one router input and ask the configured router for one decision."""
    router = build_router(orchestrator_config)
    router_input = build_router_input(
        request,
        getattr(request, "conversation_manager", None),
        _lookback(orchestrator_config),
    )
    channel_kind = getattr(request, "channel_kind", "channel")
    router_input = replace(
        router_input,
        text=_sanitize_for_routing(router_input.text),
        context=replace(router_input.context, channel_kind=channel_kind),
        config=replace(
            router_input.config,
            tau=_web_threshold(orchestrator_config, channel_kind),
        ),
    )
    decision = await router.decide(router_input)
    request.logger.info("Routing decision: %s", decision_log_fields(decision))
    return decision


def _routing_metadata(
    decision: RouteDecision,
    service: str,
    *,
    degraded: bool = False,
) -> RoutingMetadata:
    """Return the cache identity for a call made under ``decision``."""
    return RoutingMetadata(
        service=service,
        router_id=decision.router_id,
        policy_version=decision.policy_version,
        decision_source=decision.source,
        route=decision.route,
        salt=decision.cache.salt,
        cacheable=decision.cache.cacheable,
        degraded=degraded,
    )


def _request_for(
    request: AIRequest,
    decision: RouteDecision,
    service: str,
    *,
    degraded: bool = False,
) -> AIRequest:
    """Attach routing metadata to the request handed to a provider client."""
    return replace(
        request,
        routing=_routing_metadata(decision, service, degraded=degraded),
    )


async def _call_perplexity(  # noqa: PLR0913, PLR0917 - mirrors the provider call
    request: AIRequest,
    decision: RouteDecision,
    clients: AIClients,
    config: AIConfig,
    conversation_summary: list[dict] | None,
    ledger: AttemptLedger,
    *,
    degraded: bool = False,
) -> tuple[str, bool, dict | None] | None:
    """Attempt Perplexity once and record the attempt."""
    ledger.record("perplexity")
    routed = _request_for(request, decision, "perplexity", degraded=degraded)
    return await process_perplexity_message(
        routed, clients.perplexity, config.perplexity, conversation_summary
    )


async def _call_openai(  # noqa: PLR0913, PLR0917 - mirrors the provider call
    request: AIRequest,
    decision: RouteDecision,
    clients: AIClients,
    config: AIConfig,
    conversation_summary: list[dict] | None,
    ledger: AttemptLedger,
    *,
    degraded: bool = False,
) -> str | None:
    """Attempt OpenAI once and record the attempt."""
    ledger.record("openai")
    routed = _request_for(request, decision, "openai", degraded=degraded)
    return await process_openai_message(
        routed, conversation_summary, clients.openai, config.openai
    )


async def _process_only_mode(
    request: AIRequest,
    service: str,
    client: Any,
    config: AIConfig,
    conversation_summary: list[dict] | None = None,
) -> tuple[str, bool, dict | None]:
    spec = _ONLY_MODE_SPECS[service]
    request.logger.info("Running in %s-only mode", spec.label)
    service_config = getattr(config, spec.config_attr)
    routed = replace(
        request,
        routing=RoutingMetadata(
            service=spec.service,
            router_id="direct",
            policy_version="0",
            decision_source="direct",
            route="web" if service == "perplexity" else "local",
            salt=f"direct:{service}",
        ),
    )
    try:
        result = await spec.invoke(routed, client, service_config, conversation_summary)
        if result:
            content, suppress, embed = spec.normalize(result)
            _record_conversation_turn(request, content, spec.service, service_config.model)
            request.logger.info("%s success (%d chars)", spec.label, len(content))
            return content, suppress, embed

        request.logger.error("%s returned no response", spec.label)
        if spec.breaker_error is not None and get_circuit_breaker(spec.service).state == "OPEN":
            return spec.breaker_error, False, None
    except Exception:
        request.logger.exception("%s processing failed", spec.label)
        return spec.exception_error, False, None
    return spec.no_response_error, False, None


async def _process_perplexity_only_mode(
    request: AIRequest,
    perplexity_client: Any,
    config: AIConfig,
    conversation_summary: list[dict] | None = None,
) -> tuple[str, bool, dict | None]:
    """Process message using Perplexity-only mode."""
    return await _process_only_mode(
        request,
        "perplexity",
        perplexity_client,
        config,
        conversation_summary,
    )


async def _process_openai_only_mode(
    request: AIRequest,
    conversation_summary: list[dict],
    openai_client: Any,
    config: AIConfig,
) -> tuple[str, bool, dict | None]:
    """Process message using OpenAI-only mode."""
    return await _process_only_mode(
        request,
        "openai",
        openai_client,
        config,
        conversation_summary,
    )


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
    strategy. The function handles error conditions and returns a degraded
    fallback when appropriate.

    Args:
        request: An `AIRequest` containing message, user, logger and
            conversation manager.
        conversation_summary: List of messages summarizing recent context
            to pass to models (already formatted for the client API).
        clients: `AIClients` containing available OpenAI/Perplexity clients.
        config: `AIConfig` with service-specific configuration.
        orchestrator_config: Optional routing and orchestrator tuning values.

    Returns:
        A tuple of `(response_text, suppress_embeds, embed_metadata)` where
        `suppress_embeds` indicates whether to suppress embed rendering and
        `embed_metadata` contains structured citation/embed information or
        `None` when not applicable.

    Raises:
        NotImplementedError: If ``ROUTER_MODE=model`` selects the unimplemented
            model router. The message names ``docs/routing/DESIGN.md``.
        ValueError: If ``ROUTER_MODE`` is not a recognised mode.
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

    except (NotImplementedError, ValueError):
        request.logger.exception("Routing configuration error")
        raise
    except Exception:
        request.logger.exception("Unexpected error in smart orchestrator")
        return ERROR_MESSAGES["unexpected_error"], False, None


async def _process_hybrid_mode(  # noqa: PLR0911 - one return per fallback outcome
    request: AIRequest,
    conversation_summary: list[dict],
    clients: AIClients,
    config: AIConfig,
    orchestrator_config: dict | None = None,
) -> tuple[str, bool, dict | None]:
    """Handle hybrid routing between OpenAI and Perplexity.

    One decision is built before any provider call, including when a cached
    answer is served. Each provider is attempted at most once per request.
    """
    decision = await _build_route_decision(request, orchestrator_config)
    ledger = AttemptLedger()
    degraded = False

    if decision.route == "web":
        request.logger.info("Routing to Perplexity")
        res = await _call_perplexity(
            request,
            decision,
            clients,
            config,
            conversation_summary,
            ledger,
        )
        if res:
            res_content, suppress, embed = res
            _record_conversation_turn(request, res_content, "perplexity", config.perplexity.model)
            return res_content, suppress, embed
        request.logger.warning("Perplexity failed, falling back to OpenAI")
        degraded = True

    request.logger.info("Routing to OpenAI")
    res_content = await _call_openai(
        request,
        decision,
        clients,
        config,
        conversation_summary,
        ledger,
        degraded=degraded,
    )
    if res_content:
        if _detect_openai_web_inability(res_content):
            request.logger.debug(
                "Discarding OpenAI answer after web-inability reroute: length=%d",
                len(res_content),
            )
            if ledger.already_tried("perplexity"):
                request.logger.warning(
                    "Perplexity already failed in this request; returning the local "
                    "answer without a second attempt"
                )
                _record_conversation_turn(request, res_content, "openai", config.openai.model)
                return res_content, False, None
            request.logger.warning(
                "OpenAI response indicates web-inability; rerouting to Perplexity"
            )
            per_res = await _call_perplexity(
                request,
                decision,
                clients,
                config,
                conversation_summary,
                ledger,
            )
            if per_res:
                per_text, per_suppress, per_embed = per_res
                _record_conversation_turn(request, per_text, "perplexity", config.perplexity.model)
                return per_text, per_suppress, per_embed
            request.logger.warning(
                "Perplexity failed after OpenAI reroute; returning original "
                "OpenAI response as degraded fallback"
            )
            _record_conversation_turn(request, res_content, "openai", config.openai.model)
            return res_content, False, None
        _record_conversation_turn(request, res_content, "openai", config.openai.model)
        return res_content, False, None

    # If OpenAI returned no response (None/empty), attempt Perplexity as a fallback.
    if ledger.already_tried("perplexity"):
        request.logger.error("Both services failed or returned no response")
        return ERROR_MESSAGES["both_services_unavailable"], False, None

    request.logger.info("OpenAI returned no response; attempting Perplexity fallback")
    per_res = await _call_perplexity(
        request,
        decision,
        clients,
        config,
        conversation_summary,
        ledger,
    )
    if per_res:
        per_text, per_suppress, per_embed = per_res
        _record_conversation_turn(request, per_text, "perplexity", config.perplexity.model)
        return per_text, per_suppress, per_embed

    request.logger.error("Both services failed or returned no response")
    return ERROR_MESSAGES["both_services_unavailable"], False, None
