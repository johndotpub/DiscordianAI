"""Perplexity API processing with web search capabilities and citation handling.

This module handles Perplexity API interactions for web-enabled responses,
including citation extraction, Discord formatting, and thread-safe
conversation management.
"""

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
from .discord_embeds import citation_embed_formatter
from .web_scraper import is_scrapable_url, scrape_url_content

# Use centralized patterns from config


def extract_citations_from_response(
    response_text: str,
    response_citations: list[str] | None = None,
    search_results: list[dict] | None = None,
) -> tuple[str, dict[str, str]]:
    """Extract citations from Perplexity response and return cleaned text with citation mapping.

    Modern Perplexity API provides citations in metadata fields rather than inline URLs.
    This function maps citation numbers [1], [2] to URLs from the response citations field.

    Args:
        response_text (str): Raw response text from Perplexity API
        response_citations (list[str], optional): Citations array from API response metadata
        search_results (list[dict], optional): Search results with title/url/date from API response

    Returns:
        Tuple[str, Dict[str, str]]: (cleaned_text, citation_dict) where
                                   citation_dict maps citation numbers to URLs
    """
    citations = {}
    logger = logging.getLogger("discordianai.perplexity")

    # Look for citation numbers in the text using pre-compiled pattern
    citation_matches = CITATION_PATTERN.findall(response_text)
    unique_citations = list(set(citation_matches))  # Remove duplicates

    logger.debug(
        f"Citation extraction: found {len(citation_matches)} citations: {citation_matches}"
    )
    logger.debug(f"Unique citations: {unique_citations}")

    # NEW: Use citations from API response metadata (modern Perplexity format)
    # Try citations field first (direct URL array)
    if unique_citations and response_citations:
        logger.debug(f"Using API citations field: {len(response_citations)} URLs available")

        # Map citation numbers to URLs from the citations array
        for citation_num in unique_citations:
            citation_index = int(citation_num) - 1  # Convert to 0-based index
            if 0 <= citation_index < len(response_citations):
                url = response_citations[citation_index]
                citations[citation_num] = url
                logger.debug(f"Mapped citation [{citation_num}] to URL: {url}")
            else:
                logger.warning(
                    f"Citation [{citation_num}] index {citation_index} out of range for "
                    f"{len(response_citations)} URLs"
                )

    # Try search_results field as fallback (more detailed objects)
    elif unique_citations and search_results:
        logger.debug(f"Using API search_results field: {len(search_results)} results available")

        # Extract URLs from search_results objects
        search_urls = [result.get("url") for result in search_results if result.get("url")]
        logger.debug(f"Extracted {len(search_urls)} URLs from search_results")

        # Map citation numbers to URLs from search results
        for citation_num in unique_citations:
            citation_index = int(citation_num) - 1  # Convert to 0-based index
            if 0 <= citation_index < len(search_urls):
                url = search_urls[citation_index]
                citations[citation_num] = url
                logger.debug(f"Mapped citation [{citation_num}] to search result URL: {url}")
            else:
                logger.warning(
                    f"Citation [{citation_num}] index {citation_index} out of range for "
                    f"{len(search_urls)} search results"
                )

    # FALLBACK: Try to extract URLs from text (legacy format support)
    # If we have citations in text but they weren't mapped by metadata (or no metadata)
    if unique_citations and len(citations) < len(unique_citations):
        logger.debug("No API metadata citations or partial mapping, trying legacy URL extraction")
        urls = URL_PATTERN.findall(response_text)
        logger.debug(f"Legacy extraction: found {len(urls)} URLs in text: {urls[:3]}...")

        if urls:
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
                        logger.debug(
                            f"Legacy mapped citation [{citation_num}] to URL: {line_urls[0]}"
                        )

            # If we still don't have all citations mapped, try the fallback approach
            if len(citations) < len(unique_citations):
                logger.debug("Some citations not mapped by line analysis, using fallback approach")

                # Fallback: try to match by position (simple approach)
                for i, url in enumerate(urls, 1):
                    if str(i) in unique_citations and str(i) not in citations:
                        citations[str(i)] = url
                        logger.debug(f"Legacy fallback mapped citation [{i}] to URL: {url}")

    # Final debug logging
    logger.debug(f"Final citation mapping: {citations}")

    # Clean up any bare URLs in the text (if any were found in legacy mode)
    urls_for_cleanup = list(citations.values()) if citations else []
    cleaned_text = _clean_bare_urls_safely(response_text, urls_for_cleanup)

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
) -> tuple[str, bool, dict | None] | None:
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
        Optional[Tuple[str, bool, dict | None]]:
            (formatted_response_text, should_suppress_embeds, embed_data)
            or None if the API call failed.
            embed_data contains Discord embed info when citations present.

    Side Effects:
        - Updates user's conversation history via thread-safe manager
        - Logs API calls, responses, and citation processing
    """
    try:
        logger.info(f"Processing Perplexity web search request for user {user.id}")
        logger.debug(f"Query: {message[:200]}...")

        # to maintain consistency and allow rollback on failures

        # Make Perplexity API call with web search enabled
        logger.debug("Making Perplexity API call with web search")

        # Extract URLs from the message for web search
        urls_in_message = URL_PATTERN.findall(message)

        # Prepare API parameters for Perplexity
        api_params = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": message},
            ],
            "max_tokens": output_tokens,
            "temperature": 0.7,  # Slightly creative for better web search synthesis
        }

        # Enable web search and citations with intelligent URL content extraction
        if urls_in_message:
            logger.info(f"Processing {len(urls_in_message)} URL(s) for content extraction")

            # Try to scrape content from URLs for better context
            scraped_contents = []
            successful_scrapes = []

            for url in urls_in_message:
                if is_scrapable_url(url):
                    logger.debug(f"Attempting to scrape content from: {url}")
                    try:
                        scraped_content = await scrape_url_content(url, logger)
                        if scraped_content:
                            scraped_contents.append(f"Content from {url}:\n{scraped_content}")
                            successful_scrapes.append(url)
                            logger.info(
                                f"Successfully scraped {len(scraped_content)} "
                                f"characters from {url}"
                            )
                        else:
                            logger.warning(f"Web scraping returned no content for: {url}")
                    except Exception as e:
                        # ruff: noqa: TRY401
                        logger.exception(f"Web scraping failed for {url}: {e}")
                else:
                    logger.debug(f"URL not suitable for scraping: {url}")

            # Build enhanced message based on scraping results
            if scraped_contents:
                # We have scraped content - provide it directly to Perplexity
                if len(urls_in_message) == 1:
                    if message.strip() == urls_in_message[0]:
                        # User just pasted a URL - analyze the scraped content
                        enhanced_message = (
                            f"Analyze the following webpage content and provide a "
                            f"comprehensive overview:\n\n{scraped_contents[0]}"
                        )
                    else:
                        # User asked a question with a URL - answer using scraped content
                        enhanced_message = (
                            f"Answer this question based on the webpage content "
                            f"provided: {message}\n\nWebpage content:\n{scraped_contents[0]}"
                        )
                else:
                    # Multiple URLs with scraped content
                    all_content = "\n\n---\n\n".join(scraped_contents)
                    enhanced_message = (
                        f"Answer this question based on the content from these "
                        f"webpages: {message}\n\nWebpage contents:\n{all_content}"
                    )

                logger.info(
                    f"Enhanced message with scraped content from {len(successful_scrapes)} URL(s)"
                )
                logger.debug(
                    f"Total scraped content length: "
                    f"{sum(len(content) for content in scraped_contents)} characters"
                )
            else:
                # No scraped content - fall back to enhanced prompting
                logger.warning(
                    "No content could be scraped from URLs, falling back to enhanced prompting"
                )
                if len(urls_in_message) == 1:
                    url = urls_in_message[0]
                    if message.strip() == url:
                        enhanced_message = (
                            f"Please search for information about this URL and "
                            f"provide an overview: {url}"
                        )
                    else:
                        enhanced_message = (
                            f"Please search for information about this URL to help "
                            f"answer the question: {message}\nURL: {url}"
                        )
                else:
                    url_list = ", ".join(urls_in_message)
                    enhanced_message = (
                        f"Please search for information about these URLs to help "
                        f"answer: {message}\nURLs: {url_list}"
                    )

            # Update the message in the API call
            api_params["messages"][1]["content"] = enhanced_message
            logger.debug(f"Enhanced message for URL processing: {enhanced_message[:200]}...")

            # Log the full enhanced message for debugging (but truncated for readability)
            if len(enhanced_message) > 1000:
                logger.debug(
                    f"Full enhanced message ({len(enhanced_message)} chars): "
                    f"{enhanced_message[:500]}...[TRUNCATED]...{enhanced_message[-200:]}"
                )
            else:
                logger.debug(f"Full enhanced message: {enhanced_message}")

        else:
            # If no URLs, still enable web search for general queries
            logger.debug("No URLs detected, enabling general web search")

        # Enable web search capabilities (citations are included by default)

        response = await perplexity_client.chat.completions.create(**api_params)
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

            # Extract citations from API response metadata (new Perplexity format)
            response_citations = getattr(response, "citations", None)
            response_search_results = getattr(response, "search_results", None)

            logger.debug(f"API response citations metadata: {response_citations}")
            logger.debug(f"API response search_results metadata: {response_search_results}")

            # Process citations if present
            clean_text, citations = extract_citations_from_response(
                raw_response, response_citations, response_search_results
            )
            logger.debug(f"Extracted {len(citations)} citations from response")

            # Check if we processed URLs and provide helpful context about what happened
            if urls_in_message:
                # Check if we have citations from the response
                if len(citations) == 0:
                    # No citations - this could mean web scraping was used or
                    # Perplexity couldn't access URLs
                    if any(
                        "Content from" in msg.get("content", "")
                        for msg in api_params["messages"]
                        if isinstance(msg, dict)
                    ):
                        # Web scraping was used - content was provided directly to Perplexity
                        logger.debug(
                            "Web scraping content was provided to Perplexity for analysis"
                        )
                    else:
                        # No web scraping and no citations - add fallback message
                        if len(urls_in_message) == 1:
                            url_info = f"the URL {urls_in_message[0]}"
                        else:
                            url_info = f"the URLs: {', '.join(urls_in_message)}"

                        fallback_text = (
                            f"\n\n**Note**: I couldn't access {url_info} directly, "
                            f"but I've searched for related information. Some websites contain "
                            f"dynamic content, require authentication, or use JavaScript that "
                            f"web search APIs can't execute. You may need to visit the URL(s) "
                            f"directly in a browser for the full content."
                        )
                        clean_text += fallback_text
                        logger.debug(
                            f"Added URL access fallback message for {len(urls_in_message)} URL(s)"
                        )
                else:
                    # We have citations - log successful URL processing
                    logger.info(f"Successfully processed URL(s) with {len(citations)} citations")

            # Determine if we should use embed formatting
            embed_data = None
            if citation_embed_formatter.should_use_embed_for_response(citations):
                # Create embed data for Discord embed rendering
                embed, embed_metadata = citation_embed_formatter.create_citation_embed(
                    clean_text, citations, footer_text="🌐 Web search results"
                )
                embed_data = {
                    "embed": embed,
                    "citations": citations,
                    "clean_text": clean_text,
                    "embed_metadata": embed_metadata,
                }
                # For embeds, use the actual content for conversation history
                # The embed will be sent separately, but we need content for context
                formatted_text = clean_text
                # Set suppress_embeds to False to prevent Discord from auto-generating embeds,
                # since we are sending a custom citation embed instead.
                suppress_embeds = False
                logger.info(f"Created citation embed with {len(citations)} citations")
            else:
                # Fallback to plain text with markdown citations (won't be clickable)
                formatted_text = format_citations_for_discord(clean_text, citations)
                suppress_embeds = should_suppress_embeds(formatted_text)
                logger.debug("Using plain text formatting (no citations for embed)")

            logger.info(
                f"Perplexity response processed: {len(formatted_text)} chars, "
                f"{len(citations)} citations, embed_mode={embed_data is not None}, "
                f"suppress_embeds={suppress_embeds}"
            )

            # Add both user and assistant messages to conversation history (thread-safe)
            # Only add after successful response to maintain consistency
            conversation_manager.add_message(user.id, "user", message)
            conversation_manager.add_message(
                user.id,
                "assistant",
                formatted_text,
                metadata={
                    "ai_service": "perplexity",
                    "citations_count": len(citations),
                    "has_embed": embed_data is not None,
                },
            )

            return formatted_text, suppress_embeds, embed_data

        logger.error(f"Perplexity API returned invalid response structure: {response}")
        return None
