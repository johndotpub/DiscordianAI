"""Generic web scraping utilities for URL content extraction.

This module provides robust, production-ready web scraping functionality
using requests + BeautifulSoup. Designed for Docker environments and
production deployment with comprehensive error handling and logging.
"""

import asyncio
import ipaddress
import logging
import random
import re
import socket
import time
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

# Configuration constants
DEFAULT_TIMEOUT = 15  # Generous timeout for slow sites
MAX_CONTENT_LENGTH = 50000  # ~12-15k tokens worth of content
MAX_DOWNLOAD_SIZE = 1000000  # 1MB raw HTML download limit
REQUEST_RETRIES = 2
MIN_DELAY_BETWEEN_REQUESTS = 1.0  # Respectful delay between requests
MAX_DELAY_BETWEEN_REQUESTS = 3.0  # Maximum random delay
TRUNCATION_LIMIT = 8000
MIN_TEXT_LENGTH = 100
MIN_PARA_LENGTH = 50
MAX_HEADING_LENGTH = 200
MIN_PARTS_FOR_KEY_SECTIONS = 2
MIN_TOTAL_LENGTH_FOR_BODY = 200
CHUNK_SIZE = 8192

# Production-ready headers to avoid blocking
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


class WebScrapingError(Exception):
    """Base exception for web scraping errors."""


class ContentExtractionError(WebScrapingError):
    """Exception raised when content extraction fails."""


def _add_respectful_delay():
    """Add a respectful delay between requests to avoid overwhelming servers."""
    # Using random for non-cryptographic purposes (rate limiting)
    delay = random.uniform(MIN_DELAY_BETWEEN_REQUESTS, MAX_DELAY_BETWEEN_REQUESTS)  # noqa: S311
    time.sleep(delay)


def _clean_text(text: str) -> str:
    """Clean and normalize scraped text content.

    Args:
        text: Raw text content from web scraping

    Returns:
        Cleaned and normalized text
    """
    if not text:
        return ""

    # First normalize multiple newlines to max 2
    text = re.sub(r"\n\s*\n", "\n\n", text)
    # Then convert remaining single newlines to spaces (but not double newlines)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    # Finally normalize spaces
    text = re.sub(r"[ \t]+", " ", text)

    # Remove common web artifacts and navigation text
    artifacts = [
        r"Skip to content|Skip to main content|Skip navigation",
        r"Cookie|Privacy Policy|Terms of Service|Accept Cookies",
        r"Subscribe|Newsletter|Sign up|Log in|Login|Register",
        r"Share this|Follow us|Social media|Advertisement",
        r"Back to top|Scroll to top|Go to top",
    ]

    for artifact_pattern in artifacts:
        text = re.sub(artifact_pattern, "", text, flags=re.IGNORECASE)

    # Clean up any remaining double spaces from artifact removal
    text = re.sub(r"  +", " ", text)

    return text.strip()


def _remove_noise_elements(soup: BeautifulSoup) -> None:
    """Remove noise elements that don't contain useful content."""
    noise_selectors = [
        "nav",
        "footer",
        "header",
        "aside",
        "script",
        "style",
        "noscript",
        ".navigation",
        ".nav",
        ".menu",
        ".sidebar",
        ".footer",
        ".header",
        ".advertisement",
        ".ad",
        ".ads",
        ".cookie-banner",
        ".popup",
        ".social-media",
        ".share-buttons",
        ".newsletter",
        ".subscribe",
    ]
    for selector in noise_selectors:
        for elem in soup.select(selector):
            elem.decompose()


def _extract_content(soup: BeautifulSoup) -> str:
    """Extract content from any web page using production-ready generic selectors."""
    content_parts = []

    # Page title
    title = soup.find("title")
    if title and title.get_text(strip=True):
        content_parts.append(f"Title: {title.get_text(strip=True)}")

    # Meta description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        content_parts.append(f"Description: {meta_desc.get('content').strip()}")

    _remove_noise_elements(soup)

    content_selectors = [
        "main",
        "article",
        ".main",
        ".content",
        "#content",
        ".post",
        ".article",
        ".page-content",
        ".entry-content",
        ".entry",
        "body",
        '[role="main"]',
        ".main-content",
        ".post-content",
        ".readme",
        ".documentation",
        ".container .content",
        "#main-content",
        ".article-content",
        ".story-content",
        ".post",
        ".entry",
        ".article",
        ".story",
        ".markdown-body",
    ]

    main_content = _try_selectors(soup, content_selectors)
    if main_content:
        text = main_content.get_text(strip=True, separator=" ")
        if text and len(text) > MIN_TEXT_LENGTH:
            content_parts.append(f"Main content: {text}")

    # If no main content found, try extracting key sections
    if not main_content or len(content_parts) < MIN_PARTS_FOR_KEY_SECTIONS:
        _extract_key_sections(soup, content_parts)

    # Final fallback: use body content
    if not content_parts or sum(len(part) for part in content_parts) < MIN_TOTAL_LENGTH_FOR_BODY:
        _extract_body_fallback(soup, content_parts)

    return "\n\n".join(content_parts)


def _try_selectors(soup: BeautifulSoup, selectors: list[str]) -> Any:
    """Try various selectors to find main content."""
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            return element
    return None


def _extract_key_sections(soup: BeautifulSoup, content_parts: list[str]) -> None:
    """Extract headings and paragraphs as fallback."""
    headings = [
        h.get_text(strip=True)
        for h in soup.find_all(["h1", "h2", "h3"])
        if h.get_text(strip=True) and len(h.get_text(strip=True)) < MAX_HEADING_LENGTH
    ]
    if headings:
        content_parts.append(f"Key sections: {' | '.join(headings[:10])}")

    if len(content_parts) < MIN_PARTS_FOR_KEY_SECTIONS:
        paragraphs = [
            p.get_text(strip=True)
            for p in soup.find_all("p")
            if p.get_text(strip=True) and len(p.get_text(strip=True)) > MIN_PARA_LENGTH
        ]
        if paragraphs:
            content_parts.append(f"Key content: {' '.join(paragraphs[:5])}")


def _extract_body_fallback(soup: BeautifulSoup, content_parts: list[str]) -> None:
    """Extract limited body content as last resort."""
    body = soup.find("body")
    if body:
        text = body.get_text(strip=True, separator=" ")
        if text:
            if len(text) > TRUNCATION_LIMIT:
                text = text[:TRUNCATION_LIMIT] + "... [content truncated]"
            content_parts.append(f"Page content: {text}")


async def scrape_url_content(
    url: str,
    logger: logging.Logger | None = None,
    request_timeout: int = DEFAULT_TIMEOUT,
    max_content_length: int = MAX_CONTENT_LENGTH,
) -> str | None:
    """Scrape content from a URL using production-ready requests + BeautifulSoup.

    This function implements production best practices including:
    - Proper error handling and retries
    - Realistic browser headers to avoid blocking
    - Content size limits for token management
    - Comprehensive logging for debugging
    - Generic content extraction for any website

    Args:
        url: URL to scrape content from
        logger: Optional logger instance for detailed logging
        request_timeout: Request timeout in seconds
        max_content_length: Maximum content length to return

    Returns:
        Extracted content as string, or None if scraping failed
    """
    if not logger:
        logger = logging.getLogger(__name__)

    logger.info("Starting web scraping for URL: %s", url)

    try:
        if not _validate_url(url, logger):
            return None

        _add_respectful_delay()

        # Execute request asynchronously, enforcing an overall asyncio timeout
        try:
            async with asyncio.timeout(request_timeout):
                html_content = await asyncio.to_thread(
                    _fetch_content_with_retries, url, request_timeout, logger
                )
        except TimeoutError:
            logger.warning("Scrape timed out for URL: %s", url)
            return None

        if not html_content:
            return None

        soup = BeautifulSoup(html_content, "html.parser")
        content = _extract_content(soup)
        if not content:
            return None

        return _process_final_content(content, max_content_length, url, logger)

    except Exception:
        logger.exception("Unexpected error during scraping: %s", url)
        return None


def _validate_url(url: str, logger: logging.Logger) -> bool:
    """Validate URL format."""
    parsed_url = urlparse(url)
    if not parsed_url.scheme or not parsed_url.netloc:
        logger.error("Invalid URL format: %s", url)
        return False
    return True


_STOP_RETRY = object()


def _fetch_content_with_retries(url: str, timeout: int, logger: logging.Logger) -> str | None:
    """Perform HTTP request with retries."""
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    try:
        for attempt in range(REQUEST_RETRIES + 1):
            result = _fetch_attempt_with_retry_logic(session, url, attempt, timeout, logger)
            if result is _STOP_RETRY:
                return None
            if result is not None:
                return result
            if attempt < REQUEST_RETRIES:
                time.sleep(2**attempt)
    finally:
        session.close()
    return None


def _fetch_attempt_with_retry_logic(
    session: requests.Session, url: str, attempt: int, timeout: int, logger: logging.Logger
) -> str | None:
    """Perform a single fetch attempt with error handling for the retry loop."""
    try:
        return _fetch_attempt(session, url, attempt, timeout, logger)
    except requests.exceptions.RequestException as e:
        if attempt == REQUEST_RETRIES or isinstance(e, requests.exceptions.HTTPError):
            _log_fetch_error(e, url, attempt, logger)
            return _STOP_RETRY
        # Let the loop handle the sleep for non-fatal errors
        return None


def _fetch_attempt(
    session: requests.Session, url: str, attempt: int, timeout: int, logger: logging.Logger
) -> str | None:
    """Perform a single fetch attempt."""
    logger.debug("HTTP attempt %d for: %s", attempt + 1, url)
    response = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
    try:
        response.raise_for_status()

        if "text/html" not in response.headers.get("content-type", "").lower():
            return _STOP_RETRY

        try:
            if int(response.headers.get("content-length", 0)) > MAX_DOWNLOAD_SIZE:
                return _STOP_RETRY
        except (TypeError, ValueError):
            return _STOP_RETRY

        content = bytearray()
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            content.extend(chunk)
            if len(content) > MAX_DOWNLOAD_SIZE:
                break
        return bytes(content).decode("utf-8", errors="ignore")
    finally:
        response.close()


def _log_fetch_error(e: Exception, url: str, attempt: int, logger: logging.Logger) -> None:
    """Log fetch errors with appropriate detail."""
    if isinstance(e, requests.exceptions.HTTPError):
        status = e.response.status_code if e.response else "unknown"
        logger.error("HTTP %s for %s", status, url)
    else:
        logger.warning("Attempt %d failed for %s: %s", attempt + 1, url, str(e))


def _process_final_content(content: str, max_length: int, url: str, logger: logging.Logger) -> str:
    """Clean and truncate extracted content."""
    clean = re.sub(r"\s+", " ", content).strip()
    original_len = len(clean)
    if original_len > max_length:
        clean = clean[:max_length] + "\n\n[Content truncated due to length]"
    logger.info("Scraped %d chars from %s", original_len, url)
    return clean


async def _resolve_hostname(hostname: str) -> list[tuple[Any, ...]]:
    """Resolve hostnames off the main event loop."""
    return await asyncio.to_thread(
        socket.getaddrinfo,
        hostname,
        None,
        socket.AF_UNSPEC,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
    )


async def is_safe_url(url: str) -> bool:
    """Check if a URL is safe to scrape (prevents SSRF)."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not (parsed.scheme in ["http", "https"] and parsed.netloc and hostname):
            return False

        addr_info = await _resolve_hostname(hostname)
        if not addr_info:
            return False

        for _family, _, _, _, sockaddr in addr_info:
            ip_obj = ipaddress.ip_address(sockaddr[0])
            # ip.is_global filters non-public ranges
            if not ip_obj.is_global:
                return False
    except (ValueError, socket.gaierror, TypeError, OSError):
        return False
    else:
        return True


async def is_scrapable_url(url: str) -> bool:
    """Check if a URL is suitable for web scraping based on extension and safety.

    Args:
        url: URL to check

    Returns:
        True if URL appears to be scrapable and safe
    """
    if not await is_safe_url(url):
        return False

    try:
        parsed = urlparse(url)
        path = parsed.path.lower()
        skip_extensions = [
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".zip",
            ".tar",
            ".gz",
            ".rar",
            ".7z",
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".svg",
            ".webp",
            ".mp4",
            ".avi",
            ".mov",
            ".mp3",
            ".wav",
            ".flac",
            ".exe",
            ".dmg",
            ".deb",
            ".rpm",
        ]
        return not any(path.endswith(ext) for ext in skip_extensions)
    except (ValueError, TypeError):
        return False
