"""Perplexity API processing with web search capabilities and citation handling.

This module handles Perplexity API interactions through the OpenAI-compatible
client and URL scraping helpers. It also covers citation extraction, Discord
formatting, and thread-safe conversation management.
"""

import logging
import re
from typing import Any

from .api_context import api_call
from .config import (
    CITATION_PATTERN,
    DEFAULT_MAX_TOTAL_SCRAPED_CHARS,
    DEFAULT_MAX_URLS_PER_MESSAGE,
    DEFAULT_SCRAPE_DEADLINE_SECONDS,
    URL_PATTERN,
)
from .discord_embeds import citation_embed_formatter
from .error_handling import DEFAULT_API_RETRY_CONFIG, retry_with_backoff
from .message_builder import build_messages
from .message_splitter import should_suppress_embeds
from .models import AIRequest, PerplexityConfig
from .web_scraper import is_scrapable_url, scrape_url_content, scrape_urls

# Constants
CITATION_SPLIT_PARTS = 2
LINK_THRESHOLD = 2
SCRAPED_SECTION_SEPARATOR = "\n\n---\n\n"
SCRAPED_PROMPT_RESERVE = max(
    len("Analyze the following webpage content:\n\n"),
    len("Answer based on webpage content: ") + len("\n\nContent:\n"),
    len("Answer based on these webpages: ") + len("\n\nContents:\n"),
)


def extract_citations_from_response(
    response_text: str,
    response_citations: list[Any] | None = None,
    search_results: list[dict] | None = None,
) -> tuple[str, dict[str, str]]:
    """Extract numbered citations from a Perplexity response.

    Attempts to resolve numbered citation markers (e.g., "[1]") to URLs
    using metadata returned by the API (`response_citations`) or via a
    provided `search_results` mapping. If neither mapping is available, the
    function falls back to extracting URLs from the surrounding text.

    Args:
        response_text: Raw assistant response text containing citation markers.
        response_citations: Optional list of metadata items returned by the API
            which may map indices to source URLs or titles.
        search_results: Optional list of search result dicts (with `url` keys)
            that can be used to map citation indices to URLs.

    Returns:
        A tuple `(cleaned_text, citations)` where `cleaned_text` has visible
        URL occurrences normalized/removed and `citations` is a mapping from
        citation index strings (e.g., "1") to resolved URLs.
    """
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

    cleaned_text = _normalize_citation_text(response_text, citations)

    return cleaned_text, citations


def _map_from_metadata(unique: list[str], metadata: list[Any], target: dict[str, str]) -> None:
    """Map indices from metadata list."""
    for num in unique:
        idx = int(num) - 1
        if 0 <= idx < len(metadata):
            citation = metadata[idx]
            target[num] = getattr(citation, "url", citation)


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


def _normalize_citation_text(text: str, citations: dict[str, str]) -> str:
    """Normalize response text to numbered markers only (no visible URLs)."""
    if not citations:
        return text.strip()

    urls_for_cleanup = list(citations.values())

    def replace_markdown(match: re.Match[str]) -> str:
        num = match.group(1)
        url = match.group(2)
        return f"[{num}]" if citations.get(num) == url else match.group(0)

    text = re.sub(r"\[(\d+)\]\((https?://[^)]+)\)", replace_markdown, text)

    text = _clean_bare_urls_safely(text, urls_for_cleanup)

    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append(line)
            continue

        if stripped in citations.values():
            continue

        match = re.match(r"\[\s*(\d+)\s*\]\s*[:\-]?\s*(https?://\S+)", stripped)
        if match and citations.get(match.group(1)) == match.group(2):
            cleaned_lines.append(line.replace(match.group(0), f"[{match.group(1)}]"))
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def _clean_bare_urls_safely(text: str, urls: list) -> str:
    """Safely remove bare URLs that aren't part of markdown links."""
    for url in urls:
        escaped_url = re.escape(url)
        pattern = rf"(?<!\]\(){escaped_url}(?!\s*\))"
        text = re.sub(pattern, "", text)
    return text


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
        linkify: If True, replace markers with markdown links pointing to
            the resolved URLs; otherwise leave bracketed markers.

    Returns:
        The transformed text ready for posting to Discord.
    """
    if not citations:
        return text

    def replace_citation(match):
        citation_num = match.group(1)
        if citation_num not in citations:
            return match.group(0)
        if not linkify:
            return f"[{citation_num}]"
        url = citations[citation_num]
        return f"[{citation_num}]({url})"

    return CITATION_PATTERN.sub(replace_citation, text)


async def process_perplexity_message(
    request: AIRequest,
    perplexity_client: Any,
    config: PerplexityConfig,
    conversation_summary: list[dict] | None = None,
) -> tuple[str, bool, dict | None] | None:
    """Get a web-enabled response from Perplexity and format it for Discord.

    This function builds the Perplexity API parameters, optionally enhances the
    prompt with scraped URL content, calls the Perplexity API, extracts
    and formats citations.
    It returns `None` when the API call fails or times out.

    Args:
        request: An `AIRequest` containing message, user, logger and
            conversation manager.
        perplexity_client: The Perplexity client object used to make API calls.
        config: `PerplexityConfig` containing model and system message.
        conversation_summary: Optional prior conversation turns to send between
            the system message and the current user message.

    Returns:
        A tuple `(response_text, suppress_embeds, embed_metadata)` when a
        successful response is obtained, or `None` on failure/timeouts.
    """
    try:
        async with api_call("perplexity", request.logger, request) as ctx:
            urls_in_message = URL_PATTERN.findall(request.message)
            api_params = _build_api_params(
                config.model,
                config.system_message,
                request.message,
                config.output_tokens,
                history=conversation_summary,
            )

            if urls_in_message:
                api_params["messages"][-1]["content"] = await _enhance_message_with_urls(
                    request.message,
                    urls_in_message,
                    request.logger,
                    max_urls=getattr(config, "max_urls_per_message", DEFAULT_MAX_URLS_PER_MESSAGE),
                    max_total_chars=getattr(
                        config, "max_total_scraped_chars", DEFAULT_MAX_TOTAL_SCRAPED_CHARS
                    ),
                    deadline_seconds=getattr(
                        config, "scrape_deadline_seconds", DEFAULT_SCRAPE_DEADLINE_SECONDS
                    ),
                )

            response = await retry_with_backoff(
                lambda: perplexity_client.chat.completions.create(**api_params),
                DEFAULT_API_RETRY_CONFIG,
                request.logger,
            )
            ctx.set_result(response)

            return _handle_api_response(response, request, urls_in_message, api_params)

    except Exception:
        request.logger.exception("Perplexity API call failed for user %s", request.user.id)
        return None


def _build_api_params(
    model: str,
    system: str,
    user_msg: str,
    tokens: int,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    """Prepare Perplexity API call parameters."""
    return {
        "model": model,
        "messages": build_messages(system, user_msg, history),
        "max_tokens": tokens,
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

    final_text = format_citations_for_discord(fmt_text, cit_map, linkify=False)
    suppress_embeds = should_suppress_embeds(final_text, threshold=LINK_THRESHOLD)

    embed_data = None
    if cit_map:
        embed, meta = citation_embed_formatter.create_citation_embed(final_text, cit_map)
        embed_data = {"embed": embed, "citations": cit_map, "clean_text": final_text, "meta": meta}

    return final_text, suppress_embeds, embed_data


async def _enhance_message_with_urls(  # noqa: PLR0913
    message: str,
    urls: list[str],
    logger: logging.Logger,
    *,
    max_urls: int = DEFAULT_MAX_URLS_PER_MESSAGE,
    max_total_chars: int = DEFAULT_MAX_TOTAL_SCRAPED_CHARS,
    deadline_seconds: float = DEFAULT_SCRAPE_DEADLINE_SECONDS,
) -> str:
    """Enhance prompt with bounded scraped content from URLs."""
    selected_urls = urls[: max(0, max_urls)]
    dropped = len(urls) - len(selected_urls)
    if dropped > 0:
        logger.warning(
            "Dropped %d URL(s) beyond MAX_URLS_PER_MESSAGE=%d (ignored)",
            dropped,
            max_urls,
        )

    logger.info("Processing %d URL(s) for content extraction", len(selected_urls))
    scrapable_urls = [url for url in selected_urls if await is_scrapable_url(url)]

    scraped = await scrape_urls(
        scrapable_urls,
        logger,
        max_urls=max_urls,
        max_total_chars=max_total_chars,
        deadline_seconds=deadline_seconds,
        scrape_func=scrape_url_content,
    )
    section_budget = max(0, max_total_chars - SCRAPED_PROMPT_RESERVE)
    sections = _assemble_scraped_sections(scraped, section_budget, logger)

    if sections:
        return _build_scraped_message(
            message,
            selected_urls,
            [section for _, section in sections],
            [url for url, _ in sections],
            logger,
        )

    return _build_fallback_message(message, selected_urls, logger)


def _assemble_scraped_sections(
    scraped: list[tuple[str, str]], max_total_chars: int, logger: logging.Logger
) -> list[tuple[str, str]]:
    """Build labelled page sections that fit inside the aggregate character budget."""
    remaining = max(0, max_total_chars)
    sections: list[tuple[str, str]] = []
    affected = 0

    for url, content in scraped:
        prefix = f"Content from {url}:\n"
        separator = SCRAPED_SECTION_SEPARATOR if sections else ""
        if remaining <= len(prefix) + len(separator):
            affected += 1
            continue
        allowed = remaining - len(prefix) - len(separator)
        trimmed = content
        if len(content) > allowed:
            trimmed = content[:allowed]
            affected += 1
        section = prefix + trimmed
        sections.append((url, section))
        remaining -= len(separator) + len(section)

    if affected:
        logger.warning(
            "Scraped prompt content capped at %d characters "
            "(MAX_TOTAL_SCRAPED_CHARS); truncated or omitted %d page(s)",
            max_total_chars,
            affected,
        )
    return sections


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

    all_content = SCRAPED_SECTION_SEPARATOR.join(scraped)
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
