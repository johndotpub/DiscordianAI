"""Generic web scraping utilities for URL content extraction.

This module provides robust, production-ready web scraping functionality
using requests + BeautifulSoup. Designed for Docker environments and
production deployment with comprehensive error handling and logging.
"""

import asyncio
import logging
import random
import re
import time
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
    delay = random.uniform(MIN_DELAY_BETWEEN_REQUESTS, MAX_DELAY_BETWEEN_REQUESTS)
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


def _extract_content(soup: BeautifulSoup) -> str:
    """Extract content from any web page using production-ready generic selectors.

    Args:
        soup: BeautifulSoup object of the page

    Returns:
        Extracted content from the webpage
    """
    content_parts = []

    # Page title (always useful)
    title = soup.find("title")
    if title:
        title_text = title.get_text(strip=True)
        if title_text:
            content_parts.append(f"Title: {title_text}")

    # Meta description (SEO content, usually high quality)
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        desc_text = meta_desc.get("content").strip()
        if desc_text:
            content_parts.append(f"Description: {desc_text}")

    # Remove noise elements that don't contain useful content
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

    # Extract main content using comprehensive selector strategy
    content_selectors = [
        # Semantic HTML5 elements (highest priority)
        "main",
        "article",
        '[role="main"]',
        # Common content containers
        ".content",
        ".main-content",
        ".page-content",
        ".post-content",
        ".entry-content",
        ".article-content",
        ".story-content",
        # Blog and CMS patterns
        ".post",
        ".entry",
        ".article",
        ".story",
        # Documentation and markdown
        ".markdown-body",
        ".readme",
        ".documentation",
        # Generic containers
        ".container .content",
        "#content",
        "#main-content",
    ]

    main_content = None
    for selector in content_selectors:
        main_content = soup.select_one(selector)
        if main_content:
            text = main_content.get_text(strip=True, separator=" ")
            if text and len(text) > 100:  # Only use if substantial content
                content_parts.append(f"Main content: {text}")
                break

    # If no main content found, try extracting key sections
    if not main_content or len(content_parts) < 2:
        # Extract headings for structure (h1-h3 only for relevance)
        headings = []
        for heading in soup.find_all(["h1", "h2", "h3"]):
            heading_text = heading.get_text(strip=True)
            if heading_text and len(heading_text) < 200:  # Reasonable heading length
                headings.append(heading_text)

        if headings:
            content_parts.append(f"Key sections: {' | '.join(headings[:10])}")

        # Extract paragraphs if we still don't have enough content
        if len(content_parts) < 2:
            paragraphs = []
            for p in soup.find_all("p"):
                p_text = p.get_text(strip=True)
                if p_text and len(p_text) > 50:  # Substantial paragraphs only
                    paragraphs.append(p_text)
                    if len(paragraphs) >= 5:  # Limit to first 5 paragraphs
                        break

            if paragraphs:
                content_parts.append(f"Key content: {' '.join(paragraphs)}")

    # Final fallback: use body content if we still have minimal content
    if not content_parts or sum(len(part) for part in content_parts) < 200:
        body = soup.find("body")
        if body:
            text = body.get_text(strip=True, separator=" ")
            if text:
                # Limit body content to prevent overwhelming output
                if len(text) > 8000:
                    text = text[:8000] + "... [content truncated]"
                content_parts.append(f"Page content: {text}")

    return "\n\n".join(content_parts)


async def scrape_url_content(
    url: str,
    logger: logging.Logger | None = None,
    timeout: int = DEFAULT_TIMEOUT,
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
        timeout: Request timeout in seconds
        max_content_length: Maximum content length to return

    Returns:
        Extracted content as string, or None if scraping failed
    """
    if not logger:
        logger = logging.getLogger(__name__)

    logger.info("Starting web scraping for URL: %s", url)

    try:
        # Validate URL format
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            logger.error("Invalid URL format: %s", url)
            return None

        # Add respectful delay before making request
        _add_respectful_delay()

        # Perform HTTP request with retries and proper error handling
        def _fetch_content():
            session = requests.Session()
            session.headers.update(DEFAULT_HEADERS)

            for attempt in range(REQUEST_RETRIES + 1):
                try:
                    logger.debug(
                        "HTTP request attempt %d/%d for: %s", attempt + 1, REQUEST_RETRIES + 1, url,
                    )

                    response = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
                    response.raise_for_status()

                    # Check content type - only process HTML content
                    content_type = response.headers.get("content-type", "").lower()
                    if "text/html" not in content_type:
                        logger.warning("Non-HTML content type: %s for URL: %s", content_type, url)
                        return None

                    # Check content length before downloading
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > MAX_DOWNLOAD_SIZE:
                        logger.warning(
                            "Content too large (%s bytes), skipping: %s",
                            content_length,
                            url,
                        )
                        return None

                    # Download content with size limit
                    content = b""
                    for chunk in response.iter_content(chunk_size=8192):
                        content += chunk
                        if len(content) > MAX_DOWNLOAD_SIZE:
                            logger.warning("Content exceeded download limit during fetch: %s", url)
                            break

                    logger.debug("Successfully downloaded %d bytes from %s", len(content), url)
                    return content.decode("utf-8", errors="ignore")

                except requests.exceptions.Timeout:
                    logger.warning("Request timeout (attempt %d) for URL: %s", attempt + 1, url)
                    if attempt == REQUEST_RETRIES:
                        logger.exception(
                            "Final timeout after %d attempts: %s", REQUEST_RETRIES + 1, url,
                        )
                        return None

                except requests.exceptions.ConnectionError:
                    logger.warning("Connection error (attempt %d) for URL: %s", attempt + 1, url)
                    if attempt == REQUEST_RETRIES:
                        logger.exception(
                            "Final connection failure after %d attempts: %s",
                            REQUEST_RETRIES + 1,
                            url,
                        )
                        return None

                except requests.exceptions.HTTPError as e:
                    status_code = e.response.status_code if e.response else "unknown"
                    logger.exception("HTTP %s error for URL: %s", status_code, url)
                    return None  # Don't retry HTTP errors

                except requests.exceptions.RequestException:
                    logger.warning("Request error (attempt %d) for URL: %s", attempt + 1, url)
                    if attempt == REQUEST_RETRIES:
                        logger.exception(
                            "Final request failure after %d attempts: %s",
                            REQUEST_RETRIES + 1,
                            url,
                        )
                        return None

                # Wait before retry (exponential backoff)
                if attempt < REQUEST_RETRIES:
                    wait_time = 2**attempt  # 1s, 2s, 4s...
                    logger.debug("Waiting %ds before retry", wait_time)
                    time.sleep(wait_time)

            return None

        # Execute request asynchronously
        html_content = await asyncio.to_thread(_fetch_content)

        if not html_content:
            logger.warning("Failed to fetch content from URL: %s", url)
            return None

        logger.debug("Successfully fetched %d characters from %s", len(html_content), url)

        # Parse HTML content
        try:
            soup = BeautifulSoup(html_content, "html.parser")
        except Exception:
            logger.exception("Failed to parse HTML content from %s", url)
            return None

        # Extract content using generic selectors
        extracted_content = _extract_content(soup)
        logger.debug("Extracted content (%d chars)", len(extracted_content))

        if not extracted_content:
            logger.warning("No content could be extracted from URL: %s", url)
            return None

        # Clean and limit content for token management
        cleaned_content = _clean_text(extracted_content)

        if len(cleaned_content) > max_content_length:
            cleaned_content = (
                cleaned_content[:max_content_length] + "\n\n[Content truncated due to length]"
            )
            logger.info("Content truncated to %d characters", max_content_length)

        logger.info(
            "Successfully scraped and processed content from %s: %d characters",
            url,
            len(cleaned_content),
        )
        logger.debug("Scraped content preview: %s...", cleaned_content[:200])

        # Log the scraped content for debugging (as requested)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Full scraped content from %s:\n%s", url, cleaned_content)

    except Exception:
        logger.exception("Unexpected error during web scraping for %s", url)
        return None
    else:
        return cleaned_content


def is_scrapable_url(url: str) -> bool:
    """Check if a URL is suitable for web scraping.

    Args:
        url: URL to check

    Returns:
        True if URL appears to be scrapable
    """
    try:
        parsed = urlparse(url)

        # Check for valid scheme and netloc
        if not parsed.scheme or not parsed.netloc:
            return False

        # Only HTTP/HTTPS
        if parsed.scheme not in ["http", "https"]:
            return False

        # Skip file types that aren't useful for content extraction
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
