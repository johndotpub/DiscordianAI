"""Smart AI Orchestrator - production routing and response orchestration.

This module asks the routing package for one evidence-based decision per
message, then calls the selected provider, handles fallback, and records the
successful turn in conversation history.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
import os
import re
from typing import Any

from .config import (
    DEFAULT_LOOKBACK_MESSAGES_FOR_CONSISTENCY,
    DISCORD_MARKUP_PATTERN,
    get_error_messages,
)
from .error_handling import ProviderCallError, get_circuit_breaker
from .message_splitter import is_inside_rendered_code
from .models import AIClients, AIConfig, AIRequest, RoutingMetadata
from .openai_processing import process_openai_message
from .perplexity_processing import process_perplexity_message
from .routing import HeuristicRouter, build_router, decision_log_fields
from .routing.context import build_router_input
from .routing.contracts import RouteDecision
from .routing.lexicon import LexiconError
from .routing.services import ROUTE_BY_SERVICE
from .routing.text import normalise_apostrophes

# Get centralized error messages
ERROR_MESSAGES = get_error_messages()


async def _invoke_openai(request, client, service_config, summary):
    return await process_openai_message(
        request,
        summary,
        client,
        service_config,
        raise_on_failure=True,
    )


async def _invoke_perplexity(request, client, service_config, summary):
    return await process_perplexity_message(
        request,
        client,
        service_config,
        summary,
        raise_on_failure=True,
    )


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
_EARLY_WEB_INABILITY_WINDOW = 300
_QUOTED_SPAN_PATTERN = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`')
_NARRATIVE_MARKERS_PATTERN = re.compile(
    r"\b(poem|haiku|story|verse|tale|fiction|imagine|imagined|imagination|dream|"
    r"dreamed|dreamt|pretend|narrator|character|once upon a time)\b",
    re.IGNORECASE,
)

# First-person admissions that the assistant could not use live web data. A
# statement about someone else, a general explanation, or a quoted example is
# not an admission and must not discard a good local answer.
_OPENAI_WEB_INABILITY_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        (
            r"\bi(?:'m\s+(?:unable|not able)|\s+(?:can't|cannot|can not|am unable|am not able))"
            r"\s+(?:to\s+)?(?:browse|search|access)\s+(?:the\s+)?"
            r"(?:web|internet|online|real.?time|current|live|website|webpage|web page)\b"
        ),
        (
            r"\bi(?:'m\s+(?:unable|not able)|\s+(?:can't|cannot|can not|am unable|am not able))"
            r"\s+(?:to\s+)?(?:look up|check|verify|confirm|provide|retrieve|fetch)\s+"
            r"(?:current|real.?time|up.?to.?date|live)\b"
        ),
        (
            r"\bi(?:'ve\s+no|\s+(?:don't|do not|have no|haven't got|have not got))\s+"
            r"(?:have\s+)?(?:access to|the ability to access)\s+(?:the\s+)?"
            r"(?:internet|web|online|real.?time|current|live|external)\b"
        ),
        (
            r"\bi\s+(?:don't|do not)\s+have\s+(?:real.?time|current|live|up.?to.?date)\s+"
            r"(?:information|data|access)\b"
        ),
        r"\bmy\s+(?:knowledge|training)\s+(?:cutoff|cut.?off)\b",
        r"\bas of my (?:last|latest)\s+(?:update|training)\b",
        r"\bi\s+(?:am|'m)\s+(?:not equipped|not designed)\s+to\s+(?:browse|search|access)\b",
    )
]

_MODEL_SELF_REFERENCE_PATTERN = re.compile(
    r"\byour\b[^.!?\n]{0,40}\b(?:knowledge|training|cutoff|cut.?off|model|version|update)\b"
    r"|\bwhat\s+(?:model|version)\s+(?:are|is)\s+you\b",
    re.IGNORECASE,
)
_CACHE_MENTION_PATTERN = re.compile(r"<@[!&]?\d+>|<#\d+>|<a?:[A-Za-z0-9_]+:\d+>")


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


def _history_user_text(request: AIRequest) -> str:
    """Return the text stored in history for a user turn, including image labels."""
    message = (getattr(request, "message", "") or "").strip()
    images = getattr(request, "images", ()) or ()
    if not images:
        return message

    labels = []
    for image in images:
        filename = str(getattr(image, "filename", "") or "").strip()
        labels.append(f"[image: {filename}]" if filename else "[image]")
    return " ".join([*labels, message]).strip()


def _record_conversation_turn(
    request: AIRequest,
    response_text: str,
    ai_service: str,
    model: str,
) -> None:
    """Record the user prompt and assistant response in conversation history."""
    user_text = _history_user_text(request)
    response_text = str(response_text or "")
    if not user_text or not response_text.strip():
        request.logger.warning("Skipping incomplete conversation turn")
        return

    manager = getattr(request, "conversation_manager", None)
    if manager is None:
        request.logger.warning("No conversation manager; skipping history write")
        return

    conversation_key = getattr(request, "conversation_key", None)
    if conversation_key is None:
        conversation_key = request.user.id

    try:
        manager.add_message(conversation_key, "user", user_text)
        manager.add_message(
            conversation_key,
            "assistant",
            response_text,
            metadata={"ai_service": ai_service, "model": model},
        )
    except Exception as exc:  # noqa: BLE001 - history is optional; the answer is already paid for
        request.logger.warning(
            "Failed to record conversation turn for %s (%s); returning the answer",
            conversation_key,
            type(exc).__name__,
        )


def _sanitize_for_routing(message: str) -> str:
    """Strip Discord markup that can create false routing cues.

    Produces a throwaway copy used only to build a ``RouterInput``. The
    original ``request.message`` is never modified for APIs, conversation
    history, cache keys, or log output.
    """
    cleaned = DISCORD_MARKUP_PATTERN.sub("", message)
    lines = [" ".join(line.split()) for line in cleaned.splitlines()]
    return "\n".join(lines).strip()


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

    return is_inside_rendered_code(response_text, position)


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

    # Apostrophe normalisation is one-for-one, so the match offsets remain
    # valid positions in the original text used by the quote/narrative checks.
    normalised_text = normalise_apostrophes(response_text)
    for pattern in _OPENAI_WEB_INABILITY_PATTERNS:
        for match in pattern.finditer(normalised_text):
            if match.start() > _EARLY_WEB_INABILITY_WINDOW:
                continue
            if _is_quoted_text(response_text, match.start()):
                continue
            if _is_narrative_context(response_text, match.start()):
                continue
            return True
    return False


def _web_inability_reroute_allowed(decision: RouteDecision, query: str) -> bool:
    """Return True when the router's decision leaves room for a web reroute.

    Only a local decision can be rerouted, and an explicit local instruction
    or a question about the model's own knowledge always holds. Those questions
    are not live-data requests even though the lookup cue pattern matches
    their ``what is`` opener.
    """
    if _MODEL_SELF_REFERENCE_PATTERN.search(query or ""):
        return False
    if decision.route != "local":
        return False
    return not any(reason.startswith("override:local") for reason in decision.reasons)


def _reroute_decision(decision: RouteDecision) -> RouteDecision:
    """Return the decision metadata for the one Perplexity reroute attempt."""
    return replace(
        decision,
        route="web",
        reasons=("override:web_reroute",),
    )


def _vision_decision(decision: RouteDecision) -> RouteDecision:
    """Force an image-bearing request onto the OpenAI-compatible provider."""
    return replace(
        decision,
        route="local",
        reasons=("images:local",),
        deterministic_override=True,
    )


def _local_fallback_decision(request: AIRequest) -> RouteDecision:
    """Return a deterministic local decision that needs no lexicon or history."""
    return RouteDecision(
        route="local",
        reasons=("fallback:lexicon_error",),
        text=getattr(request, "message", "") or "",
    )


def _cacheable(decision: RouteDecision) -> bool:
    """Return True when the answer produced under ``decision`` may be cached."""
    if any(reason.startswith("override:url") for reason in decision.reasons):
        return False
    if decision.route == "local" and any(
        reason.startswith("bearing:") for reason in decision.reasons
    ):
        return False
    return any(character.isalnum() for character in _CACHE_MENTION_PATTERN.sub("", decision.text))


def _lookback(orchestrator_config: dict | None) -> int:
    """Return the configured follow-up lookback window."""
    if not orchestrator_config:
        return DEFAULT_LOOKBACK_MESSAGES_FOR_CONSISTENCY
    return orchestrator_config.get(
        "LOOKBACK_MESSAGES_FOR_CONSISTENCY", DEFAULT_LOOKBACK_MESSAGES_FOR_CONSISTENCY
    )


_DEFAULT_ROUTERS: dict[tuple[Any, ...], Any] = {}


def _configured_router_value(config: Mapping | None, key: str) -> Any:
    """Return the value ``build_router`` would read for ``key``."""
    if isinstance(config, Mapping):
        if key in config:
            return config[key]
    elif config is not None and hasattr(config, key):
        return getattr(config, key)
    return os.environ.get(key)


def _eligible_key_value(config: Mapping | None, key: str) -> str | None:
    """Return a non-blank config value, a non-blank environment value, or None."""
    value = _configured_router_value(config, key)
    if value is not None and str(value).strip():
        return str(value).strip()
    env_value = os.environ.get(key)
    if env_value is not None and env_value.strip():
        return env_value.strip()
    return None


def _router_cache_key(config: Mapping | None) -> tuple[Any, ...]:
    """Return a hashable snapshot of every setting ``build_router`` reads."""
    return (
        build_router,
        _configured_router_value(config, "ROUTER_MODE"),
        _eligible_key_value(config, "ROUTER_CLEF_API_KEY"),
        os.environ.get("OLLAMA_API_KEY"),
        _eligible_key_value(config, "OPENAI_API_KEY"),
        _configured_router_value(config, "OPENAI_API_URL"),
        _configured_router_value(config, "ROUTER_CLEF_MODEL"),
        _configured_router_value(config, "ROUTER_CLEF_THRESHOLD"),
        _configured_router_value(config, "ROUTER_CLEF_TIMEOUT_MS"),
    )


def _default_router(config: Mapping | None) -> Any:
    """Return the fallback router, built once per effective configuration.

    Production injects the startup router. Direct callers that do not inject
    one still pay for at most one construction per configuration instead of
    rebuilding the router for every message.
    """
    key = _router_cache_key(config)
    cached = _DEFAULT_ROUTERS.get(key)
    if cached is None:
        cached = build_router(config)
        _DEFAULT_ROUTERS[key] = cached
    return cached


async def _build_route_decision(
    request: AIRequest,
    orchestrator_config: dict | None,
    router: Any | None = None,
) -> RouteDecision:
    """Build one router input and ask the configured router for one decision.

    A router that fails at runtime falls back to the deterministic gate with a
    logged reason. Configuration errors for a retired or unknown mode still
    propagate so startup and direct callers fail loudly.
    """
    try:
        active_router = router if router is not None else _default_router(orchestrator_config)
        router_input = build_router_input(
            request,
            getattr(request, "conversation_manager", None),
            _lookback(orchestrator_config),
        )
        router_input = replace(
            router_input,
            text=_sanitize_for_routing(router_input.text),
        )
    except LexiconError as exc:
        return _lexicon_fallback_decision(request, exc)
    except (NotImplementedError, ValueError):
        raise
    except Exception as exc:
        request.logger.exception(
            "Routing setup failed (%s); falling back to a deterministic local decision",
            type(exc).__name__,
        )
        return _local_fallback_decision(request)

    try:
        return await active_router.decide(router_input)
    except LexiconError as exc:
        return _lexicon_fallback_decision(request, exc)
    except Exception as exc:
        request.logger.exception(
            "Router failed (%s); falling back to the deterministic gate",
            type(exc).__name__,
        )
        try:
            gate_decision = HeuristicRouter().decide_sync(router_input)
        except Exception:
            request.logger.exception("Deterministic gate failed; using a local decision")
            return _local_fallback_decision(request)
        return replace(
            gate_decision,
            reasons=("fallback:router_error", *gate_decision.reasons),
        )


def _lexicon_fallback_decision(request: AIRequest, exc: Exception) -> RouteDecision:
    """Log a lexicon failure once and return a local fallback decision."""
    request.logger.error(
        "Routing lexicon failed; falling back to a deterministic local decision (%s)",
        type(exc).__name__,
        exc_info=exc,
    )
    return _local_fallback_decision(request)


def _routing_metadata(
    decision: RouteDecision,
    service: str,
    *,
    degraded: bool = False,
) -> RoutingMetadata:
    """Return the cache identity for a call made under ``decision``."""
    rerouted = "override:web_reroute" in decision.reasons
    suffix = ":reroute" if rerouted else ""
    return RoutingMetadata(
        service=service,
        router_id=decision.router_id,
        policy_version=decision.policy_version,
        decision_source=decision.reasons[0] if decision.reasons else "unknown",
        route=decision.route,
        salt=f"{decision.route}:{decision.router_id}:{decision.policy_version}{suffix}",
        cacheable=_cacheable(decision),
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
            route=ROUTE_BY_SERVICE[service],
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
    except ProviderCallError as failure:
        return failure.details.user_message, False, None
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


async def get_smart_response(  # noqa: PLR0913 - the injected router
    request: AIRequest,
    conversation_summary: list[dict],
    clients: AIClients,
    config: AIConfig,
    orchestrator_config: dict | None = None,
    *,
    router: Any | None = None,
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
        router: Optional process-wide router built once at startup.

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
            if getattr(request, "images", ()):
                request.logger.warning(
                    "Image request needs the OpenAI-compatible provider; "
                    "refusing to send images to Perplexity"
                )
                return ERROR_MESSAGES["vision_unavailable"], False, None
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
                request,
                conversation_summary,
                clients,
                config,
                orchestrator_config,
                router=router,
            )

        request.logger.critical("No AI clients available")
        return ERROR_MESSAGES["configuration_error"], False, None

    except (NotImplementedError, ValueError):
        request.logger.exception("Routing configuration error")
        raise
    except Exception:
        request.logger.exception("Unexpected error in smart orchestrator")
        return ERROR_MESSAGES["unexpected_error"], False, None


async def _process_hybrid_mode(  # noqa: PLR0911, PLR0913 - one branch per fallback outcome
    request: AIRequest,
    conversation_summary: list[dict],
    clients: AIClients,
    config: AIConfig,
    orchestrator_config: dict | None = None,
    *,
    router: Any | None = None,
) -> tuple[str, bool, dict | None]:
    """Handle hybrid routing between OpenAI and Perplexity.

    An image request is decided before any router runs. Otherwise one decision
    is built before any provider call, including when a cached answer is served.
    Each provider is attempted at most once per request.
    """
    ledger = AttemptLedger()
    degraded = False

    if getattr(request, "images", ()):
        decision = _vision_decision(
            RouteDecision(
                route="local",
                reasons=("images:local",),
                text=getattr(request, "message", "") or "",
            )
        )
    else:
        decision = await _build_route_decision(request, orchestrator_config, router)
    request.logger.info("Routing decision: %s", decision_log_fields(decision))

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
            if getattr(request, "images", ()):
                request.logger.info(
                    "Image request answered locally; not rerouting to Perplexity without images"
                )
                _record_conversation_turn(request, res_content, "openai", config.openai.model)
                return res_content, False, None
            if not _web_inability_reroute_allowed(decision, request.message):
                request.logger.info(
                    "OpenAI response mentions web-inability, but the routing decision "
                    "holds; keeping the local answer"
                )
                _record_conversation_turn(request, res_content, "openai", config.openai.model)
                return res_content, False, None
            request.logger.debug(
                "Discarding OpenAI answer after web-inability reroute: length=%d",
                len(res_content),
            )
            request.logger.warning(
                "OpenAI response indicates web-inability; rerouting to Perplexity"
            )
            per_res = await _call_perplexity(
                request,
                _reroute_decision(decision),
                clients,
                config,
                conversation_summary,
                ledger,
                degraded=True,
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
    if getattr(request, "images", ()):
        request.logger.error(
            "The OpenAI-compatible provider returned no response for an image request; "
            "Perplexity cannot receive images, so there is no fallback"
        )
        return ERROR_MESSAGES["ai_service_unavailable"], False, None

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
