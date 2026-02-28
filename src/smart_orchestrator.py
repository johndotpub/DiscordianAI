"""Smart AI Orchestrator - Production-Grade Clean Architecture.

This module intelligently decides which AI service to use for each message
and orchestrates the response generation with comprehensive error handling,
logging, and thread-safe conversation management.
"""

from typing import Any

from .config import (
    COMPILED_CONVERSATIONAL_PATTERNS,
    COMPILED_ENTITY_PATTERNS,
    COMPILED_FACTUAL_PATTERNS,
    COMPILED_FOLLOW_UP_PATTERNS,
    COMPILED_TIME_SENSITIVITY_PATTERNS,
    COMPILED_URL_DETECTION_PATTERNS,
    get_error_messages,
)
from .conversation_manager import ThreadSafeConversationManager
from .models import AIClients, AIConfig, AIRequest
from .openai_processing import process_openai_message
from .perplexity_processing import process_perplexity_message

# Get centralized error messages
ERROR_MESSAGES = get_error_messages()

# Constants for magic values
DEFAULT_LOOKBACK = 6
MAX_ORCHESTRATOR_RETURNS = 6


def has_time_sensitivity(message: str) -> bool:
    """Check if message implies current/recent information is needed."""
    return any(pattern.search(message) for pattern in COMPILED_TIME_SENSITIVITY_PATTERNS)


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
) -> bool:
    """Intelligently determine if a message needs web search."""
    # PRIORITY CHECK: If message contains URLs, always use web search
    if any(pattern.search(message) for pattern in COMPILED_URL_DETECTION_PATTERNS):
        return True

    # Check conversation context
    if conversation_manager and user_id:
        has_follow_up = any(pattern.search(message) for pattern in COMPILED_FOLLOW_UP_PATTERNS)
        if has_follow_up:
            recent_ai_service = conversation_manager.get_recent_ai_service(
                user_id,
                lookback_messages=lookback_messages,
            )
            if recent_ai_service:
                return recent_ai_service == "perplexity"

    # If it's clearly conversational or creative, don't use web search
    if is_conversational_or_creative(message):
        return False

    # Positive indicators for web search
    return (
        has_time_sensitivity(message)
        or is_factual_query(message)
        or any(p.search(message) for p in COMPILED_ENTITY_PATTERNS)
    )


async def _process_perplexity_only_mode(
    request: AIRequest,
    perplexity_client: Any,
    config: AIConfig,
) -> tuple[str, bool, dict | None]:
    """Process message using Perplexity-only mode."""
    request.logger.info("Running in Perplexity-only mode")
    try:
        result = await process_perplexity_message(request, perplexity_client, config.perplexity)
        if result:
            res_content, suppress, embed = result
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
            request.logger.info("OpenAI success (%d chars)", len(response_content))
            return response_content, False, None

        request.logger.error("OpenAI returned no response")
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
    """Choose the best AI service and generate a response."""
    try:
        request.logger.info("Orchestrating response for user %s", request.user.id)

        # Mode 1: Perplexity only
        if clients.perplexity and not clients.openai:
            return await _process_perplexity_only_mode(request, clients.perplexity, config)

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

    needs_web = should_use_web_search(
        request.message,
        request.conversation_manager,
        request.user.id,
        lookback_messages=lookback,
    )

    if needs_web:
        request.logger.info("Routing to Perplexity")
        res = await process_perplexity_message(request, clients.perplexity, config.perplexity)
        if res:
            return res
        request.logger.warning("Perplexity failed, falling back to OpenAI")

    request.logger.info("Routing to OpenAI")
    res_content = await process_openai_message(
        request, conversation_summary, clients.openai, config.openai
    )
    if res_content:
        return res_content, False, None

    request.logger.error("Both services failed or returned no response")
    return ERROR_MESSAGES["both_services_unavailable"], False, None
