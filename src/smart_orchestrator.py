"""Smart AI Orchestrator - Production-Grade Clean Architecture.

This module intelligently decides which AI service to use for each message
and orchestrates the response generation with comprehensive error handling,
logging, and thread-safe conversation management.
"""

import re

from .config import get_error_messages
from .conversation_manager import ThreadSafeConversationManager
from .openai_processing import process_openai_message
from .perplexity_processing import process_perplexity_message

# Get centralized error messages
ERROR_MESSAGES = get_error_messages()

# Compiled regex patterns for better performance (cached globally)
_TIME_SENSITIVITY_PATTERNS = [
    re.compile(
        r"\b(today|yesterday|this week|this month|this year|recently|latest|current|now)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(2024|2025|2026)\b", re.IGNORECASE),  # Recent/current years
    re.compile(r"\b(what.*happening|what.*happened)\b", re.IGNORECASE),
    re.compile(
        r"\b(current|recent|new|latest).*\b(news|update|information|data|report)\b", re.IGNORECASE
    ),
]

_FACTUAL_PATTERNS = [
    re.compile(
        r"\b(what|who|when|where|how much|how many).*\b(is|are|was|were|will|would|cost|price)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(weather|temperature|forecast|stock|price|market|news|events|schedule|score|game)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(status|condition|situation|state).*of\b", re.IGNORECASE),
    re.compile(r"\bhow.*doing\b", re.IGNORECASE),
    re.compile(r"\b(better|worse|faster|slower|higher|lower|more|less).*than\b", re.IGNORECASE),
]

_CONVERSATIONAL_PATTERNS = [
    re.compile(
        r"\b(hello|hi|hey|good morning|good evening|how are you|what\'s up)\b", re.IGNORECASE
    ),
    re.compile(r"\b(what do you think|your opinion|do you like|do you prefer)\b", re.IGNORECASE),
    re.compile(
        r"\b(write|create|make|generate|tell me).*\b(story|poem|joke|song|script)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(how to|help me|explain|teach|show me).*\b(code|program|function|algorithm)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(meaning|purpose|philosophy|theory|concept|idea)\b", re.IGNORECASE),
]

_ENTITY_PATTERNS = [
    re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b"),  # Proper names
    re.compile(r"\b[A-Z]{2,}\b"),  # Acronyms/companies
    re.compile(r"\$[A-Z]+\b"),  # Stock symbols
]

_FOLLOW_UP_PATTERNS = [
    re.compile(
        r"\b(continue|more|follow.?up|also|additionally|furthermore|moreover)\b", re.IGNORECASE
    ),
    re.compile(r"\b(what about|how about|tell me more)\b", re.IGNORECASE),
    re.compile(r"\b(and|but|however|though|although)\b.*\?", re.IGNORECASE),
    re.compile(r"^(yes|no|ok|okay),", re.IGNORECASE),  # Responses that continue conversation
]


def has_time_sensitivity(message: str) -> bool:
    """Check if message implies current/recent information is needed.

    Analyzes message content for time-sensitive keywords and phrases that
    indicate the user is asking for current or recent information that
    would benefit from web search capabilities.

    Args:
        message (str): The user's message to analyze

    Returns:
        bool: True if the message appears to be time-sensitive

    Examples:
        >>> has_time_sensitivity("What happened today in the news?")
        True
        >>> has_time_sensitivity("What is Python programming?")
        False
    """
    # Use pre-compiled patterns for better performance
    return any(pattern.search(message) for pattern in _TIME_SENSITIVITY_PATTERNS)


def is_factual_query(message: str) -> bool:
    """Check if message is asking for factual information that might change over time.

    Identifies queries that request specific factual information, especially
    data that changes frequently and would benefit from current web search.

    Args:
        message (str): The user's message to analyze

    Returns:
        bool: True if the message appears to be a factual query

    Examples:
        >>> is_factual_query("What is the current price of Bitcoin?")
        True
        >>> is_factual_query("How do I write a Python function?")
        False
    """
    # Use pre-compiled patterns for better performance
    return any(pattern.search(message) for pattern in _FACTUAL_PATTERNS)


def is_conversational_or_creative(message: str) -> bool:
    """Check if message is conversational, creative, or personal in nature.

    Identifies messages that are more suited to conversational AI responses
    rather than web search, including greetings, creative requests, and
    personal interactions.

    Args:
        message (str): The user's message to analyze

    Returns:
        bool: True if the message appears conversational or creative

    Examples:
        >>> is_conversational_or_creative("Hello! How are you?")
        True
        >>> is_conversational_or_creative("Write me a story about robots")
        True
        >>> is_conversational_or_creative("What's the current weather?")
        False
    """
    # Use pre-compiled patterns for better performance
    return any(pattern.search(message) for pattern in _CONVERSATIONAL_PATTERNS)


def should_use_web_search(
    message: str,
    conversation_manager: ThreadSafeConversationManager | None = None,
    user_id: int | None = None,
    lookback_messages: int = 6,
    entity_detection_min_words: int = 10,
) -> bool:
    """Intelligently determine if a message needs web search based on semantic analysis.

    This is the core decision-making function that determines whether to route
    a query to web search (Perplexity) or conversational AI (OpenAI) based on
    the content and context of the message.

    Args:
        message (str): The user's message to analyze
        conversation_manager (Optional[ThreadSafeConversationManager]):
            Conversation manager for context
        user_id (Optional[int]): User ID for retrieving recent AI service usage
        lookback_messages (int): How many recent messages to check for consistency (default: 6)
        entity_detection_min_words (int): Minimum words before checking entities (default: 10)

    Returns:
        bool: True if web search would likely provide better/more current information

    Decision Logic:
        1. Check conversation context for ongoing topics (for consistency)
        2. Conversational/creative messages -> False (use ChatGPT)
        3. Time-sensitive messages -> True (use web search)
        4. Factual queries -> True (use web search)
        5. Long specific queries with entities -> True (use web search)
        6. Default -> False (use ChatGPT)
    """
    # Check conversation context for ongoing topics to maintain consistency
    if conversation_manager and user_id:
        # Check for follow-up indicators using pre-compiled patterns
        has_follow_up = any(pattern.search(message) for pattern in _FOLLOW_UP_PATTERNS)

        if has_follow_up:
            # Use metadata-based service detection instead of fragile heuristics
            recent_ai_service = conversation_manager.get_recent_ai_service(
                user_id, lookback_messages=lookback_messages
            )

            if recent_ai_service:
                # Maintain consistency with previous AI choice for follow-ups
                return recent_ai_service == "perplexity"

    # If it's clearly conversational or creative, don't use web search
    if is_conversational_or_creative(message):
        return False

    # If it has time sensitivity, definitely use web search
    if has_time_sensitivity(message):
        return True

    # If it's a factual query, lean towards web search
    if is_factual_query(message):
        return True

    # Check message length and complexity
    # (longer, more specific questions often benefit from web search)
    if len(message.split()) > entity_detection_min_words:
        return any(pattern.search(message) for pattern in _ENTITY_PATTERNS)

    # Default to False for general conversation
    return False


async def _process_perplexity_only_mode(
    message: str,
    user,
    conversation_manager,
    logger,
    perplexity_client,
    system_message: str,
    output_tokens: int,
    model: str = "sonar-pro",
) -> tuple[str, bool]:
    """Process message using Perplexity-only mode."""
    logger.info("Running in Perplexity-only mode")
    try:
        result = await process_perplexity_message(
            message,
            user,
            conversation_manager,
            logger,
            perplexity_client,
            system_message,
            output_tokens,
            model,
        )
        if result:
            response_content, suppress_embeds = result
            logger.info(
                f"Perplexity response generated successfully ({len(response_content)} chars)"
            )
            return response_content, suppress_embeds
        logger.error("Perplexity API returned no response")
        return ERROR_MESSAGES["no_response_generated"], False

    except Exception:
        logger.exception("Perplexity processing failed")
        return ERROR_MESSAGES["web_search_unavailable"], False


async def _process_openai_only_mode(
    message: str,
    user,
    conversation_summary,
    conversation_manager,
    logger,
    openai_client,
    gpt_model: str,
    system_message: str,
    output_tokens: int,
) -> tuple[str, bool]:
    """Process message using OpenAI-only mode."""
    logger.info("Running in OpenAI-only mode")
    try:
        response_content = await process_openai_message(
            message,
            user,
            conversation_summary,
            conversation_manager,
            logger,
            openai_client,
            gpt_model,
            system_message,
            output_tokens,
        )
        if response_content:
            logger.info(f"OpenAI response generated successfully ({len(response_content)} chars)")
            return response_content, False
        logger.error("OpenAI API returned no response")
        return ERROR_MESSAGES["no_response_generated"], False

    except Exception:
        logger.exception("OpenAI processing failed")
        return ERROR_MESSAGES["ai_service_unavailable"], False


async def _try_perplexity_with_fallback(
    message: str,
    user,
    conversation_manager,
    logger,
    perplexity_client,
    system_message: str,
    output_tokens: int,
    model: str = "sonar-pro",
) -> tuple[str | None, bool]:
    """Try Perplexity API with fallback handling."""
    logger.info(
        "Message analysis suggests web search would be beneficial - trying Perplexity first"
    )
    try:
        result = await process_perplexity_message(
            message,
            user,
            conversation_manager,
            logger,
            perplexity_client,
            system_message,
            output_tokens,
            model,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Perplexity failed in hybrid mode, falling back to OpenAI: %s", e)
        return None, False
    else:
        if result:
            response_content, suppress_embeds = result
            logger.info(
                f"Perplexity response successful in hybrid mode ({len(response_content)} chars)"
            )
            return response_content, suppress_embeds
        logger.warning("Perplexity returned no response, falling back to OpenAI")
        return None, False


async def _process_hybrid_mode(
    message: str,
    user,
    conversation_manager,
    logger,
    openai_client,
    perplexity_client,
    gpt_model: str,
    system_message: str,
    output_tokens: int,
    config: dict | None = None,
) -> tuple[str, bool]:
    """Process message using hybrid mode with intelligent service selection."""
    logger.info("Running in hybrid mode - analyzing message for optimal routing")

    # Get configuration values with fallback defaults
    lookback_messages = config.get("LOOKBACK_MESSAGES_FOR_CONSISTENCY", 6) if config else 6
    entity_min_words = config.get("ENTITY_DETECTION_MIN_WORDS", 10) if config else 10

    needs_web = should_use_web_search(
        message,
        conversation_manager,
        user.id,
        lookback_messages=lookback_messages,
        entity_detection_min_words=entity_min_words,
    )

    # Try Perplexity first if web search is beneficial
    if needs_web:
        perplexity_model = config.get("PERPLEXITY_MODEL", "sonar-pro") if config else "sonar-pro"
        response_content, suppress_embeds = await _try_perplexity_with_fallback(
            message,
            user,
            conversation_manager,
            logger,
            perplexity_client,
            system_message,
            output_tokens,
            perplexity_model,
        )
        if response_content:
            return response_content, suppress_embeds
    else:
        logger.info("Message analysis suggests conversational AI is optimal - using OpenAI")

    # Use OpenAI (either as first choice or fallback)
    fresh_conversation_summary = conversation_manager.get_conversation_summary_formatted(user.id)
    try:
        response_content = await process_openai_message(
            message,
            user,
            fresh_conversation_summary,
            conversation_manager,
            logger,
            openai_client,
            gpt_model,
            system_message,
            output_tokens,
        )

        if response_content:
            logger.info(
                f"OpenAI response successful in hybrid mode ({len(response_content)} chars)"
            )
            return response_content, False
        logger.error("OpenAI returned no response in hybrid mode")
        return ERROR_MESSAGES["no_response_generated"], False

    except Exception:
        logger.exception("OpenAI failed in hybrid mode")
        return ERROR_MESSAGES["both_services_unavailable"], False


async def get_smart_response(
    message: str,
    user,
    conversation_summary,
    conversation_manager,  # Now using thread-safe manager instead of dict
    logger,
    openai_client,
    perplexity_client,
    gpt_model: str,
    system_message: str,
    output_tokens: int,
    config: dict | None = None,  # Configuration dictionary with orchestrator settings
) -> tuple[str, bool]:
    """Choose the best AI service and generate a response with robust error handling.

    This is the main orchestration function that analyzes the user's message,
    selects the most appropriate AI service, handles the conversation state
    in a thread-safe manner, and returns the response with embed suppression info.

    Supports three operation modes:
    1. GPT only (if perplexity_client is None)
    2. Perplexity only (if openai_client is None)
    3. Hybrid mode (both available) - automatically chooses best option

    Args:
        message (str): User's input message
        user: Discord user object
        conversation_summary: Summary of conversation history
        conversation_manager: Thread-safe conversation manager
        logger: Logger for orchestration events
        openai_client: OpenAI client instance (may be None)
        perplexity_client: Perplexity client instance (may be None)
        gpt_model (str): GPT model identifier
        system_message (str): System prompt for AI
        output_tokens (int): Maximum output tokens
        config (dict, optional): Configuration dictionary with orchestrator settings

    Returns:
        Tuple[str, bool]: (response_text, should_suppress_embeds)

    Raises:
        Exception: Critical errors that prevent any response generation
    """
    try:
        logger.info(
            f"Smart orchestrator processing message from user {user.id}: {message[:100]}..."
        )

        # Mode 1: Perplexity only
        if perplexity_client and not openai_client:
            perplexity_model = (
                config.get("PERPLEXITY_MODEL", "sonar-pro") if config else "sonar-pro"
            )
            return await _process_perplexity_only_mode(
                message,
                user,
                conversation_manager,
                logger,
                perplexity_client,
                system_message,
                output_tokens,
                perplexity_model,
            )

        # Mode 2: OpenAI only
        if openai_client and not perplexity_client:
            return await _process_openai_only_mode(
                message,
                user,
                conversation_summary,
                conversation_manager,
                logger,
                openai_client,
                gpt_model,
                system_message,
                output_tokens,
            )

        # Mode 3: Hybrid mode
        if openai_client and perplexity_client:
            return await _process_hybrid_mode(
                message,
                user,
                conversation_manager,
                logger,
                openai_client,
                perplexity_client,
                gpt_model,
                system_message,
                output_tokens,
                config,
            )

        # Fallback if no clients available (shouldn't happen due to config validation)
        logger.critical("No AI service clients available - this indicates a configuration error")
        return ERROR_MESSAGES["configuration_error"], False

    except Exception as e:
        logger.critical("Unexpected error in smart orchestrator: %s", e, exc_info=True)
        return ERROR_MESSAGES["unexpected_error"], False
