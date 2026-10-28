"""Generic web scraping utilities for URL content extraction.

This module provides robust, production-ready web scraping functionality
using httpx + BeautifulSoup. Designed for Docker environments and
production deployment with comprehensive error handling and logging.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import ipaddress
import logging
import re
import secrets
import socket
from typing import Any
from urllib.parse import ParseResult, urljoin, urlparse, urlunsplit

from bs4 import BeautifulSoup
import httpx

from .config import (
    DEFAULT_MAX_TOTAL_SCRAPED_CHARS,
    DEFAULT_MAX_URLS_PER_MESSAGE,
    DEFAULT_SCRAPE_DEADLINE_SECONDS,
)

# Configuration constants
DEFAULT_TIMEOUT = 15  # Generous timeout for slow sites
MAX_CONTENT_LENGTH = 50000  # ~12-15k tokens worth of content
MAX_DOWNLOAD_SIZE = 1000000  # 1MB raw HTML download limit
REQUEST_RETRIES = 2
RATE_LIMIT_MAX_RETRY_AFTER = 30.0
HTTP_STATUS_TOO_MANY_REQUESTS = 429
HTTP_STATUS_SERVER_ERROR = 500
HTTP_STATUS_SERVER_ERROR_MAX = 600
MIN_DELAY_BETWEEN_REQUESTS = 1.0  # Respectful delay between requests
MAX_DELAY_BETWEEN_REQUESTS = 3.0  # Maximum random delay
MAX_CONCURRENT_HOSTS = 2  # Distinct hosts scraped at once
TRUNCATION_LIMIT = 8000
MIN_TEXT_LENGTH = 100
MIN_PARA_LENGTH = 50
MAX_HEADING_LENGTH = 200
MIN_PARTS_FOR_KEY_SECTIONS = 2
MIN_TOTAL_LENGTH_FOR_BODY = 200
CHUNK_SIZE = 8192
MAX_REDIRECTS = 3
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
MAX_TCP_PORT = 65535
NAT64_NETWORK = ipaddress.ip_network("64:ff9b::/96")

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


class _StopRetry:
    """Sentinel indicating the retry loop should stop immediately."""


class _RetryAfter:
    """Retry delay requested by a server response."""

    def __init__(self, delay: float):
        self.delay = delay


@dataclass(frozen=True)
class _Redirect:
    """A validated redirect target waiting to be followed."""

    url: str


@dataclass(frozen=True)
class _ValidatedUrl:
    """A URL whose hostname resolved exclusively to global addresses."""

    url: str
    parsed: ParseResult
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]


_STOP_RETRY = _StopRetry()


async def _add_respectful_delay():
    """Add a respectful delay between requests to avoid overwhelming servers."""
    # Using SystemRandom to stay consistent with the jitter helpers.
    delay = secrets.SystemRandom().uniform(MIN_DELAY_BETWEEN_REQUESTS, MAX_DELAY_BETWEEN_REQUESTS)
    await asyncio.sleep(delay)


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
    """Scrape content from a URL using production-ready httpx + BeautifulSoup.

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
        target = await _resolve_safe_target(url, logger)
        if target is None:
            logger.warning("Refusing to scrape unsafe URL: %s", url)
            return None

        # Execute request asynchronously, enforcing an overall asyncio timeout
        try:
            async with asyncio.timeout(request_timeout):
                html_content = await _fetch_content_with_retries(target, request_timeout, logger)
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


@dataclass
class _HostState:
    """Politeness state for one host during a batch scrape."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    requested: bool = False


def _host_key(url: str) -> str:
    """Return a normalized hostname used to group scrape requests."""
    try:
        hostname = urlparse(url).hostname
    except ValueError:
        return ""
    return (hostname or "").lower()


async def _scrape_host_worker(  # noqa: PLR0913, PLR0917
    indices: list[int],
    urls: list[str],
    state: _HostState,
    results: dict[int, str],
    semaphore: asyncio.Semaphore,
    logger: logging.Logger,
    scrape_func: Callable[..., Awaitable[str | None]],
    request_timeout: int,
    max_content_length: int,
) -> None:
    """Scrape one host's URLs serially, delaying only between requests."""
    for index in indices:
        async with state.lock:
            if state.requested:
                await _add_respectful_delay()
            state.requested = True

            async with semaphore:
                try:
                    content = await scrape_func(
                        urls[index],
                        logger,
                        request_timeout=request_timeout,
                        max_content_length=max_content_length,
                    )
                except (TimeoutError, httpx.HTTPError):
                    logger.exception("Web scraping failed for %s", urls[index])
                    content = None

            if content:
                results[index] = content


def _apply_total_content_budget(
    contents: list[tuple[str, str]], max_total_chars: int, logger: logging.Logger
) -> list[tuple[str, str]]:
    """Trim collected page content so its combined length stays within budget."""
    remaining = max(0, max_total_chars)
    kept: list[tuple[str, str]] = []
    affected = 0

    for url, content in contents:
        if remaining <= 0:
            affected += 1
            continue
        trimmed = content
        if len(content) > remaining:
            trimmed = content[:remaining]
            affected += 1
        kept.append((url, trimmed))
        remaining -= len(trimmed)

    if affected:
        logger.warning(
            "Scraped content capped at %d characters "
            "(MAX_TOTAL_SCRAPED_CHARS); truncated or omitted %d page(s)",
            max_total_chars,
            affected,
        )
    return kept


async def scrape_urls(  # noqa: PLR0913
    urls: list[str],
    logger: logging.Logger | None = None,
    *,
    max_urls: int = DEFAULT_MAX_URLS_PER_MESSAGE,
    max_total_chars: int = DEFAULT_MAX_TOTAL_SCRAPED_CHARS,
    deadline_seconds: float = DEFAULT_SCRAPE_DEADLINE_SECONDS,
    request_timeout: int = DEFAULT_TIMEOUT,
    max_content_length: int = MAX_CONTENT_LENGTH,
    scrape_func: Callable[..., Awaitable[str | None]] | None = None,
) -> list[tuple[str, str]]:
    """Scrape a bounded batch of URLs with per-host politeness and one deadline.

    URLs beyond ``max_urls`` are ignored. Distinct hosts are scraped
    concurrently under a small semaphore, while requests to the same host stay
    serialized and observe a politeness delay between requests. The combined
    returned content never exceeds ``max_total_chars``.

    Args:
        urls: Candidate URLs to scrape.
        logger: Optional logger for scrape diagnostics.
        max_urls: Maximum number of URLs to process from this batch.
        max_total_chars: Maximum combined characters returned across pages.
        deadline_seconds: Deadline for the entire scrape phase.
        request_timeout: Timeout for each individual HTTP request.
        max_content_length: Per-page content length passed to the scraper.
        scrape_func: Optional scraper override, primarily for testing.

    Returns:
        A list of ``(url, content)`` pairs in the original URL order.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    limit = max(0, max_urls)
    selected = list(urls[:limit])
    dropped = len(urls) - len(selected)
    if dropped > 0:
        logger.warning(
            "Dropped %d URL(s) beyond MAX_URLS_PER_MESSAGE=%d (ignored)",
            dropped,
            max_urls,
        )

    if not selected:
        return []

    if deadline_seconds <= 0:
        logger.warning(
            "Scrape deadline of %ss reached; using 0 partial result(s)",
            deadline_seconds,
        )
        return []

    scraper = scrape_func or scrape_url_content
    grouped: dict[str, list[int]] = {}
    for index, url in enumerate(selected):
        grouped.setdefault(_host_key(url), []).append(index)

    results: dict[int, str] = {}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_HOSTS)
    states = {host: _HostState() for host in grouped}
    tasks = [
        asyncio.create_task(
            _scrape_host_worker(
                indices,
                selected,
                states[host],
                results,
                semaphore,
                logger,
                scraper,
                request_timeout,
                max_content_length,
            )
        )
        for host, indices in grouped.items()
    ]

    try:
        async with asyncio.timeout(deadline_seconds):
            await asyncio.gather(*tasks)
    except TimeoutError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.warning(
            "Scrape deadline of %ss reached; using %d partial result(s)",
            deadline_seconds,
            len(results),
        )

    ordered = [(selected[index], results[index]) for index in sorted(results)]
    return _apply_total_content_budget(ordered, max_total_chars, logger)


def _format_authority(host: str, port: int | None, scheme: str) -> str:
    """Format a hostname and optional port for an HTTP Host header."""
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if scheme == "https" else 80
    if port is not None and port != default_port:
        host = f"{host}:{port}"
    return host


def _pinned_request_url(target: _ValidatedUrl) -> tuple[str, str]:
    """Build an HTTP request URL pinned to the first vetted address."""
    parsed = target.parsed
    ip = target.addresses[0]
    ip_host = f"[{ip}]" if isinstance(ip, ipaddress.IPv6Address) else str(ip)
    netloc = f"{ip_host}:{parsed.port}" if parsed.port is not None else ip_host
    request_url = urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))
    host_header = _format_authority(parsed.hostname or "", parsed.port, parsed.scheme)
    return request_url, host_header


async def _fetch_content_with_retries(
    target: _ValidatedUrl, request_timeout: int, logger: logging.Logger
) -> str | None:
    """Perform HTTP request with retries."""
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=False) as client:
        for attempt in range(REQUEST_RETRIES + 1):
            result = await _fetch_attempt_with_retry_logic(
                client, target, attempt, request_timeout, logger
            )
            delay = 2**attempt
            if isinstance(result, _RetryAfter):
                delay = result.delay
                result = None
            if result is _STOP_RETRY:
                return None
            if result is not None:
                return result
            if attempt < REQUEST_RETRIES:
                await asyncio.sleep(delay)
    return None


def _is_retryable_http_status(status_code: int | None) -> bool:
    """Return whether an HTTP status represents a transient server-side failure."""
    return status_code == HTTP_STATUS_TOO_MANY_REQUESTS or (
        status_code is not None
        and HTTP_STATUS_SERVER_ERROR <= status_code < HTTP_STATUS_SERVER_ERROR_MAX
    )


def _retry_after_delay(response) -> float | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    try:
        value = headers.get("Retry-After")
    except (AttributeError, TypeError):
        return None

    if value is None:
        return None

    try:
        delay = float(str(value).strip())
    except (TypeError, ValueError):
        return None

    return min(max(delay, 0.0), RATE_LIMIT_MAX_RETRY_AFTER)


async def _fetch_attempt_with_retry_logic(  # noqa: PLR0911
    client: httpx.AsyncClient,
    target: _ValidatedUrl,
    attempt: int,
    request_timeout: int,
    logger: logging.Logger,
) -> str | _StopRetry | _RetryAfter | None:
    """Perform a single fetch attempt, following only validated redirects."""
    redirects_followed = 0
    while True:
        try:
            result = await _fetch_attempt(client, target, attempt, request_timeout, logger)
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code if e.response is not None else None
            if attempt == REQUEST_RETRIES or not _is_retryable_http_status(status_code):
                _log_fetch_error(e, target.url, attempt, logger)
                return _STOP_RETRY
            if status_code == HTTP_STATUS_TOO_MANY_REQUESTS:
                delay = _retry_after_delay(e.response)
                if delay is not None:
                    return _RetryAfter(delay)
            return None
        except httpx.TimeoutException as e:
            if attempt == REQUEST_RETRIES or not isinstance(e, httpx.ConnectTimeout):
                _log_fetch_error(e, target.url, attempt, logger)
                return _STOP_RETRY
            return None
        except httpx.HTTPError as e:
            if attempt == REQUEST_RETRIES:
                _log_fetch_error(e, target.url, attempt, logger)
                return _STOP_RETRY
            # Let the loop handle the sleep for non-fatal errors
            return None

        if not isinstance(result, _Redirect):
            return result

        if redirects_followed >= MAX_REDIRECTS:
            logger.warning(
                "Refusing redirect chain longer than %d hops: %s", MAX_REDIRECTS, target.url
            )
            return _STOP_RETRY

        redirect_target = await _resolve_safe_target(result.url, logger)
        if redirect_target is None:
            logger.warning("Refusing redirect to unsafe URL: %s", result.url)
            return _STOP_RETRY

        redirects_followed += 1
        logger.info(
            "Following redirect %d/%d to %s", redirects_followed, MAX_REDIRECTS, result.url
        )
        target = redirect_target


async def _fetch_attempt(
    client: httpx.AsyncClient,
    target: _ValidatedUrl,
    attempt: int,
    request_timeout: int,
    logger: logging.Logger,
) -> str | _StopRetry | _Redirect:
    """Perform a single request without following redirects."""
    request_url = target.url
    request_headers: dict[str, str] | None = None

    # Plain HTTP is pinned to the vetted IP via the URL and Host header. HTTPS
    # is deliberately not pinned: connecting to a bare address would break SNI
    # and certificate validation. The hostname was resolved and every address
    # checked immediately before this request, but httpx resolves it again when
    # connecting, leaving a small DNS-rebinding window. That residual risk is
    # documented in docs/Security.md.
    if target.parsed.scheme == "http":
        request_url, host_header = _pinned_request_url(target)
        request_headers = {"Host": host_header}

    logger.debug("HTTP attempt %d for: %s", attempt + 1, target.url)
    async with client.stream(
        "GET", request_url, timeout=request_timeout, headers=request_headers
    ) as response:
        if response.status_code in REDIRECT_STATUS_CODES:
            location = response.headers.get("location")
            if not location:
                logger.warning("Redirect without Location header from %s", target.url)
                return _STOP_RETRY
            return _Redirect(urljoin(target.url, location))

        response.raise_for_status()

        if "text/html" not in response.headers.get("content-type", "").lower():
            return _STOP_RETRY

        try:
            if int(response.headers.get("content-length", 0)) > MAX_DOWNLOAD_SIZE:
                return _STOP_RETRY
        except (TypeError, ValueError):
            pass

        content = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
            remaining = MAX_DOWNLOAD_SIZE - len(content)
            if remaining <= 0:
                break
            if len(chunk) > remaining:
                content.extend(chunk[:remaining])
                break
            content.extend(chunk)
        return bytes(content).decode("utf-8", errors="ignore")


def _log_fetch_error(e: Exception, url: str, attempt: int, logger: logging.Logger) -> None:
    """Log fetch errors with appropriate detail."""
    if isinstance(e, httpx.HTTPStatusError):
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


def _is_global_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True only for routable public addresses.

    IPv4-mapped IPv6 addresses are unwrapped before checking so loopback,
    private, link-local and CGNAT mappings cannot slip through. NAT64
    addresses are unwrapped for the same reason, and multicast is never a
    valid scrape target.
    """
    if isinstance(address, ipaddress.IPv6Address):
        mapped = address.ipv4_mapped
        if mapped is not None:
            address = mapped
        elif address in NAT64_NETWORK:
            address = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return address.is_global and not address.is_multicast


async def _resolve_safe_target(  # noqa: PLR0911
    url: str, logger: logging.Logger
) -> _ValidatedUrl | None:
    """Resolve a URL once and accept it only if every address is global."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
        if port is not None and not 0 < port <= MAX_TCP_PORT:
            logger.warning("Invalid port in URL: %s", url)
            return None
    except ValueError:
        logger.warning("Invalid URL: %s", url)
        return None

    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname:
        logger.warning("Invalid URL scheme or host: %s", url)
        return None

    try:
        addr_info = await _resolve_hostname(hostname)
    except (socket.gaierror, TypeError, OSError) as e:
        logger.warning("Could not resolve %s: %s", hostname, e)
        return None

    if not addr_info:
        logger.warning("No addresses resolved for %s", hostname)
        return None

    addresses = []
    for _family, _, _, _, sockaddr in addr_info:
        try:
            ip_obj = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
        except (ValueError, TypeError, IndexError):
            logger.warning("Invalid resolved address for %s", hostname)
            return None
        if not _is_global_address(ip_obj):
            logger.warning("Refusing %s: %s is not a global address", url, ip_obj)
            return None
        addresses.append(ip_obj)

    return _ValidatedUrl(url=url, parsed=parsed, addresses=tuple(addresses))


async def is_safe_url(url: str) -> bool:
    """Check if a URL is safe to scrape (prevents SSRF)."""
    target = await _resolve_safe_target(url, logging.getLogger(__name__))
    return target is not None


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
