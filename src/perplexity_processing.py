"""Perplexity API processing with web search capabilities and citation handling.

This module handles Perplexity API interactions for web-enabled responses,
including citation extraction, Discord formatting, and thread-safe
conversation management.
"""

import logging
import re
from typing import Any

from .config import (
    BARE_URL_PATTERN,
    CITATION_PATTERN,
    LINK_PATTERN,
    URL_PATTERN,
)
from .discord_embeds import citation_embed_formatter
from .models import AIRequest, PerplexityConfig
from .web_scraper import is_scrapable_url, scrape_url_content

# Constants
CITATION_SPLIT_PARTS = 2
LINK_THRESHOLD = 2


def _extract_per_citation(cit: Any, idx: int) -> tuple[str, str] | None:
    """Extract single citation details from various possible formats."""
    if isinstance(cit, str):
        if not cit.strip():
            return None
        parts = cit.split(" - ", 1)
        if len(parts) == CITATION_SPLIT_PARTS:
            return parts[0].strip(), parts[1].strip()
        return f"Source {idx}", cit.strip()
    if isinstance(cit, dict):
        url = cit.get("url") or cit.get("link")
        title = cit.get("title") or cit.get("name") or f"Source {idx}"
        if url:
            return title, url
    return None


def extract_citations_from_response(
    response_text: str,
    response_citations: list[Any] | None = None,
    search_results: list[dict] | None = None,
) -> tuple[str, dict[str, str]]:
    """Extract citations from response using metadata or fallback extraction."""
    citations = {}

    citation_matches = CITATION_PATTERN.findall(response_text)
    unique_citations = list(set(citation_matches))

    if not unique_citations:
        return response_text, {}

    # Try different mapping strategies
    if response_citations:
        _map_from_metadata(unique_citations, response_citations, citations)
    elif search_results:
        _map_from_search_results(unique_citations, search_results, citations)

    # Fallback to text extraction if mapping is incomplete
    if len(citations) < len(unique_citations):
        _map_from_text_fallback(response_text, unique_citations, citations)

    # Clean up results
    urls_for_cleanup = list(citations.values()) if citations else []
    cleaned_text = _clean_bare_urls_safely(response_text, urls_for_cleanup)

    return cleaned_text.strip(), citations


def _map_from_metadata(unique: list[str], metadata: list[Any], target: dict[str, str]) -> None:
    """Map indices from metadata list."""
    for num in unique:
        idx = int(num) - 1
        if 0 <= idx < len(metadata):
            target[num] = metadata[idx]


def _map_from_search_results(
    unique: list[str], results: list[dict], target: dict[str, str]
) -> None:
    """Map indices from result URLs."""
    urls = [r.get("url") for r in results if r.get("url")]
    for num in unique:
        idx = int(num) - 1
        if 0 <= idx < len(urls):
            target[num] = urls[idx]


def _map_from_text_fallback(text: str, unique: list[str], target: dict[str, str]) -> None:
    """Fallback: extract URLs directly from line context."""
    for line in text.split("\n"):
        match = CITATION_PATTERN.search(line)
        if match:
            num = match.group(1)
            if num in unique and num not in target:
                urls = URL_PATTERN.findall(line)
                if urls:
                    target[num] = urls[0]


def _clean_bare_urls_safely(text: str, urls: list) -> str:
    """Safely remove bare URLs that aren't part of markdown links."""
    for url in urls:
        escaped_url = re.escape(url)
        pattern = rf"(?<!\]\(){escaped_url}(?!\s*\))"
        text = re.sub(pattern, "", text)
    return text


def format_citations_for_discord(text: str, citations: dict[str, str]) -> str:
    """Convert numbered citations to Discord-compatible hyperlinks."""
    if not citations:
        return text

    def replace_citation(match):
        citation_num = match.group(1)
        if citation_num in citations:
            url = citations[citation_num]
            return f"[{citation_num}]({url})"
        return match.group(0)

    return CITATION_PATTERN.sub(replace_citation, text)


def should_suppress_embeds(text: str) -> bool:
    """Determine if a message should suppress embeds."""
    links = LINK_PATTERN.findall(text)
    urls = BARE_URL_PATTERN.findall(text)
    total_links = len(links) + len(urls)

    return total_links >= LINK_THRESHOLD


async def process_perplexity_message(
    request: AIRequest,
    perplexity_client: Any,
    config: PerplexityConfig,
) -> tuple[str, bool, dict | None] | None:
    """Get response from Perplexity with web-enabled model and error handling."""
    try:
        request.logger.info("Processing Perplexity request for user %s", request.user.id)

        urls_in_message = URL_PATTERN.findall(request.message)
        api_params = _build_api_params(
            config.model, config.system_message, request.message, config.output_tokens
        )

        if urls_in_message:
            api_params["messages"][1]["content"] = await _enhance_message_with_urls(
                request.message, urls_in_message, request.logger
            )

        response = await perplexity_client.chat.completions.create(**api_params)
        return _handle_api_response(response, request, urls_in_message, api_params)

    except TimeoutError:
        request.logger.exception("Perplexity API call timed out for user %s", request.user.id)
        return None
    except Exception:
        request.logger.exception("Perplexity API call failed for user %s", request.user.id)
        return None


def _build_api_params(model: str, system: str, user_msg: str, tokens: int) -> dict[str, Any]:
    """Prepare Perplexity API call parameters."""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": tokens,
        "temperature": 0.7,
    }


def _handle_api_response(
    response: Any,
    request: AIRequest,
    urls_in_message: list[str],
    api_params: dict[str, Any],
) -> tuple[str, bool, dict | None] | None:
    """Process and format the API response."""
    if not (response.choices and response.choices[0].message.content):
        return None

    raw_response = response.choices[0].message.content.strip()
    if not raw_response:
        request.logger.warning("Perplexity returned empty response content")
        return None

    res_cit = getattr(response, "citations", None)
    search_res = getattr(response, "search_results", None)

    fmt_text, cit_map = extract_citations_from_response(raw_response, res_cit, search_res)

    # Restore the "Note: I couldn't access" logic for tests
    messages = api_params.get("messages", [])
    has_scraped = any("Content from" in m.get("content", "") for m in messages)

    if urls_in_message and not cit_map and not has_scraped:
        url_info = (
            f"the URL {urls_in_message[0]}"
            if len(urls_in_message) == 1
            else f"{len(urls_in_message)} URLs"
        )
        fmt_text = (
            f"**Note**: I couldn't access {url_info} directly, "
            f"but based on my search: \n\n{fmt_text}"
        )

    final_text = format_citations_for_discord(fmt_text, cit_map)
    suppress_embeds = should_suppress_embeds(final_text)

    embed_data = None
    if cit_map:
        embed, meta = citation_embed_formatter.create_citation_embed(final_text, cit_map)
        embed_data = {"embed": embed, "citations": cit_map, "clean_text": final_text, "meta": meta}

    # Persist
    request.conversation_manager.add_message(request.user.id, "assistant", final_text)
    return final_text, suppress_embeds, embed_data


async def _enhance_message_with_urls(message: str, urls: list[str], logger: logging.Logger) -> str:
    """Enhance prompt with scraped content from URLs."""
    logger.info("Processing %d URL(s) for content extraction", len(urls))
    scraped_contents = []
    successful_scrapes = []

    for url in urls:
        if is_scrapable_url(url):
            try:
                content = await scrape_url_content(url, logger)
                if content:
                    scraped_contents.append(f"Content from {url}:\n{content}")
                    successful_scrapes.append(url)
            except Exception:
                logger.exception("Web scraping failed for %s", url)

    if scraped_contents:
        return _build_scraped_message(message, urls, scraped_contents, successful_scrapes, logger)

    return _build_fallback_message(message, urls, logger)


def _build_scraped_message(
    message: str,
    urls: list[str],
    scraped: list[str],
    successful: list[str],
    logger: logging.Logger,
) -> str:
    """Build message when scraping was successful."""
    logger.info("Enhanced message with scraped content from %d URL(s)", len(successful))
    if len(urls) == 1 and message.strip() == urls[0]:
        return f"Analyze the following webpage content:\n\n{scraped[0]}"

    if len(urls) == 1:
        return f"Answer based on webpage content: {message}\n\nContent:\n{scraped[0]}"

    all_content = "\n\n---\n\n".join(scraped)
    return f"Answer based on these webpages: {message}\n\nContents:\n{all_content}"


def _build_fallback_message(message: str, urls: list[str], logger: logging.Logger) -> str:
    """Build message when scraping failed."""
    logger.warning("Scraping failed, using fallback prompting")
    if len(urls) == 1 and message.strip() == urls[0]:
        return f"Please search for information about this URL and provide an overview: {urls[0]}"

    if len(urls) == 1:
        return (
            f"Please search for information about this URL to help answer: {message}\n"
            f"URL: {urls[0]}"
        )

    url_list = ", ".join(urls)
    return (
        f"Please search for information about these URLs to help answer: {message}\n"
        f"URLs: {url_list}"
    )
