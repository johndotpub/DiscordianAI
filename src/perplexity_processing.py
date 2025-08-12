"""Perplexity API processing with web search capabilities and citation handling.

This module handles Perplexity API interactions for web-enabled responses,
including citation extraction, Discord formatting, and thread-safe
conversation management.
"""

import asyncio
import logging
import re

from .caching import cached_response, deduplicated_request
from .config import (
    BARE_URL_PATTERN,
    CITATION_PATTERN,
    DEFAULT_CACHE_TTL,
    LINK_PATTERN,
    URL_PATTERN,
)
from .conversation_manager import ThreadSafeConversationManager

# Use centralized patterns from config


def extract_citations_from_response(response_text: str) -> tuple[str, dict[str, str]]:
    """Extract citations from Perplexity response and return cleaned text with citation mapping.

    Perplexity typically includes citations at the end of lines in format [1], [2] etc.
    This function extracts these citations and maps them to URLs found in the text.

    Args:
        response_text (str): Raw response text from Perplexity API

    Returns:
        Tuple[str, Dict[str, str]]: (cleaned_text, citation_dict) where
                                   citation_dict maps citation numbers to URLs
    """
    citations = {}

    # Look for citation numbers in the text using pre-compiled pattern
    citation_matches = CITATION_PATTERN.findall(response_text)

    # Look for URLs in the text
    urls = URL_PATTERN.findall(response_text)

    # Debug logging for citation extraction
    logger = logging.getLogger("discordianai.perplexity")
    logger.debug(
        f"Citation extraction: found {len(citation_matches)} citations: {citation_matches}"
    )
    logger.debug(
        f"Citation extraction: found {len(urls)} URLs: {urls[:3]}..."
    )  # Show first 3 URLs

    # Since Perplexity citations are always at the end of lines,
    # we can use a more intelligent approach to match citations to URLs

    if citation_matches and urls:
        # Split text into lines to find citations at line endings
        lines = response_text.split("\n")

        for line in lines:
            # Look for citations at the end of each line
            citation_match = CITATION_PATTERN.search(line)
            if citation_match:
                citation_num = citation_match.group(1)

                # Find URLs in this specific line
                line_urls = URL_PATTERN.findall(line)

                if line_urls:
                    # Use the first URL found in the line with the citation
                    citations[citation_num] = line_urls[0]
                    logger.debug(f"Mapped citation [{citation_num}] to URL: {line_urls[0]}")

        # If we still don't have all citations mapped, try the fallback approach
        if len(citations) < len(citation_matches):
            logger.debug("Some citations not mapped by line analysis, using fallback approach")

            # Fallback: try to match by position (simple approach)
            for i, url in enumerate(urls, 1):
                if str(i) in citation_matches and str(i) not in citations:
                    citations[str(i)] = url
                    logger.debug(f"Fallback mapped citation [{i}] to URL: {url}")

    # Final debug logging
    logger.debug(f"Final citation mapping: {citations}")

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
    while preserving the citation numbers for readability.

    Args:
        text (str): Text with [1], [2] style citations
        citations (Dict[str, str]): Mapping of citation numbers to URLs

    Returns:
        str: Text with Discord hyperlink format: [1](url), [2](url)
    """
    if not citations:
        return text

    def replace_citation(match):
        citation_num = match.group(1)
        if citation_num in citations:
            url = citations[citation_num]
            # Keep the citation number as the display text for readability
            return f"[{citation_num}]({url})"
        return match.group(0)  # Return original if no URL found

    # Replace [1], [2], etc. with Discord hyperlinks using pre-compiled pattern
    return CITATION_PATTERN.sub(replace_citation, text)


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
    links = LINK_PATTERN.findall(text)

    # Also count bare URLs that might generate embeds using pre-compiled pattern
    urls = BARE_URL_PATTERN.findall(text)

    total_links = len(links) + len(urls)

    # Suppress embeds if there are 2 or more links to prevent clutter
    return total_links >= 2


@cached_response(ttl=DEFAULT_CACHE_TTL)
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
    except TimeoutError:
        logger.exception(f"Perplexity API call timed out for user {user.id}")
        return None
    except Exception:
        logger.exception("Perplexity API call failed for user %s", user.id)
        # Log additional context for debugging
        logger.debug(f"Failed Perplexity call context - Message length: {len(message)}")
        # Don't add failed responses to conversation history
        return None
    else:
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
