"""Perplexity API processing with web search capabilities and citation handling.

This module handles Perplexity API interactions for web-enabled responses,
including citation extraction, Discord formatting, and thread-safe
conversation management.
"""

import asyncio
import logging
import re

from .caching import cached_response, deduplicated_request
from .conversation_manager import ThreadSafeConversationManager

# Pre-compile regex patterns for better performance (cached globally)
_CITATION_PATTERN = re.compile(r"\[(\d+)\]")
_URL_PATTERN = re.compile(r"https?://[^\s\[\]()]+[^\s\[\]().,;!?]")
_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BARE_URL_PATTERN = re.compile(r"https?://[^\s]+")


def extract_citations_from_response(response_text: str) -> tuple[str, dict[str, str]]:
    """Extract citations from Perplexity response and return cleaned text with citation mapping.

    Perplexity typically includes citations in format [1], [2] etc. This function
    attempts to extract and map these citations to URLs when available.

    Args:
        response_text (str): Raw response text from Perplexity API

    Returns:
        Tuple[str, Dict[str, str]]: (cleaned_text, citation_dict) where
                                   citation_dict maps citation numbers to URLs
    """
    citations = {}

    # Look for citation numbers in the text using pre-compiled pattern
    citation_matches = _CITATION_PATTERN.findall(response_text)

    # Look for URLs in the text and try to match them to citations using pre-compiled pattern
    # This is a fallback approach until we can access full Perplexity metadata
    urls = _URL_PATTERN.findall(response_text)

    # Create a simple mapping for any URLs found
    for i, url in enumerate(urls, 1):
        if str(i) in citation_matches:
            citations[str(i)] = url

    # Clean up any bare URLs in the text since we'll be converting citations to hyperlinks
    cleaned_text = _clean_bare_urls_safely(response_text, urls)

    return cleaned_text.strip(), citations


def _clean_bare_urls_safely(text: str, urls: list) -> str:
    """Safely remove bare URLs that aren't part of markdown links.

    This prevents accidentally removing URLs from legitimate markdown links
    or corrupting message content through global replacements.

    Args:
        text (str): The text to clean
        urls (list): List of URLs to potentially remove

    Returns:
        str: Text with bare URLs removed safely
    """
    for url in urls:
        # Use regex to only remove URLs not inside markdown links
        # Pattern matches URL only when it's not part of [text](url) structure
        escaped_url = re.escape(url)
        pattern = rf"(?<!\]\(){escaped_url}(?!\s*\))"
        text = re.sub(pattern, "", text)

    return text


def format_citations_for_discord(text: str, citations: dict[str, str]) -> str:
    """Convert numbered citations to Discord-compatible hyperlinks.

    Transforms citation numbers like [1], [2] into clickable Discord hyperlinks
    using markdown format with domain names as display text.

    Args:
        text (str): Text with [1], [2] style citations
        citations (Dict[str, str]): Mapping of citation numbers to URLs

    Returns:
        str: Text with Discord hyperlink format: [domain](url)
    """
    if not citations:
        return text

    def replace_citation(match):
        citation_num = match.group(1)
        if citation_num in citations:
            url = citations[citation_num]
            # Extract domain name for display
            try:
                domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
                domain = domain_match.group(1) if domain_match else url
                # Clean up domain for display
                domain = domain.split("/")[0].split("?")[0]
                return f"[{domain}]({url})"
            except Exception:
                return f"[source]({url})"
        return match.group(0)  # Return original if no URL found

    # Replace [1], [2], etc. with Discord hyperlinks using pre-compiled pattern
    return _CITATION_PATTERN.sub(replace_citation, text)


def should_suppress_embeds(text: str) -> bool:
    """Determine if a message should suppress embeds to prevent link preview clutter.

    Analyzes message content to determine if automatic embed suppression
    would improve readability by reducing visual clutter from multiple
    link previews.

    Args:
        text (str): Message text to analyze

    Returns:
        bool: True if embeds should be suppressed (2+ links detected)
    """
    # Count Discord hyperlinks [title](url) using pre-compiled pattern
    links = _LINK_PATTERN.findall(text)

    # Also count bare URLs that might generate embeds using pre-compiled pattern
    urls = _BARE_URL_PATTERN.findall(text)

    total_links = len(links) + len(urls)

    # Suppress embeds if there are 2 or more links to prevent clutter
    return total_links >= 2


@cached_response(ttl=180.0)  # Cache for 3 minutes (shorter due to web content)
@deduplicated_request()
async def process_perplexity_message(
    message: str,
    user,
    conversation_manager: ThreadSafeConversationManager,
    logger: logging.Logger,
    perplexity_client,
    system_message: str = (
        "You are a helpful assistant with access to current web information. "
        "When providing citations, include source URLs when available."
    ),
    output_tokens: int = 8000,
    model: str = "sonar-pro",
) -> tuple[str, bool] | None:
    """Get response from Perplexity's web-enabled model with comprehensive error handling.

    Processes user queries through Perplexity's web search capabilities,
    handles citation extraction and formatting, and manages conversation
    state in a thread-safe manner.

    Args:
        message (str): User's input message
        user: Discord user object
        conversation_manager (ThreadSafeConversationManager): Thread-safe conversation manager
        logger (logging.Logger): Logger for API events and errors
        perplexity_client: OpenAI client configured for Perplexity
        system_message (str): System prompt for the AI
        output_tokens (int): Maximum tokens to generate
        model (str): Perplexity model to use (default: "sonar-pro")

    Returns:
        Optional[Tuple[str, bool]]: (formatted_response_text, should_suppress_embeds)
                                   or None if the API call failed

    Side Effects:
        - Updates user's conversation history via thread-safe manager
        - Logs API calls, responses, and citation processing
    """
    try:
        logger.info(f"Processing Perplexity web search request for user {user.id}")
        logger.debug(f"Query: {message[:200]}...")

        # Note: We'll add user message to conversation history only after successful response
        # to maintain consistency and allow rollback on failures

        # Make Perplexity API call
        logger.debug("Making Perplexity API call")
        response = await asyncio.to_thread(
            lambda: perplexity_client.chat.completions.create(
                model=model,  # Configurable Perplexity model
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": message},
                ],
                max_tokens=output_tokens,
                temperature=0.7,  # Slightly creative for better web search synthesis
            )
        )

        # Log response metadata
        logger.debug(
            f"Perplexity API response received - ID: {getattr(response, 'id', 'unknown')}"
        )
        if hasattr(response, "usage"):
            usage = response.usage
            logger.info(
                f"Perplexity token usage - Prompt: {getattr(usage, 'prompt_tokens', 'unknown')}, "
                f"Completion: {getattr(usage, 'completion_tokens', 'unknown')}, "
                f"Total: {getattr(usage, 'total_tokens', 'unknown')}"
            )

        # Extract and process response
        if response.choices and response.choices[0].message.content:
            raw_response = response.choices[0].message.content.strip()

            if not raw_response:
                logger.warning("Perplexity returned empty response content")
                return None

            logger.debug(f"Raw Perplexity response: {len(raw_response)} characters")
            logger.debug(f"Response preview: {raw_response[:200]}...")

            # Process citations if present
            clean_text, citations = extract_citations_from_response(raw_response)
            logger.debug(f"Extracted {len(citations)} citations from response")

            # Format citations for Discord
            formatted_text = format_citations_for_discord(clean_text, citations)

            # Determine if embeds should be suppressed
            suppress_embeds = should_suppress_embeds(formatted_text)

            logger.info(
                f"Perplexity response processed: {len(formatted_text)} chars, "
                f"{len(citations)} citations, suppress_embeds={suppress_embeds}"
            )

            # Add both user and assistant messages to conversation history (thread-safe)
            # Only add after successful response to maintain consistency
            conversation_manager.add_message(user.id, "user", message)
            conversation_manager.add_message(
                user.id,
                "assistant",
                formatted_text,
                metadata={"ai_service": "perplexity", "citations_count": len(citations)},
            )

            return formatted_text, suppress_embeds

        logger.error(f"Perplexity API returned invalid response structure: {response}")
        return None

    except TimeoutError:
        logger.exception(f"Perplexity API call timed out for user {user.id}")
        return None

    except Exception as e:
        logger.error(
            f"Perplexity API call failed for user {user.id}: {type(e).__name__}: {e}",
            exc_info=True,
        )

        # Log additional context for debugging
        logger.debug(f"Failed Perplexity call context - Message length: {len(message)}")

        # Don't add failed responses to conversation history
        return None
