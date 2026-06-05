"""Tests for web scraping functionality."""

import logging
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.web_scraper import (
    MAX_DOWNLOAD_SIZE,
    WebScrapingError,
    _clean_text,
    _extract_content,
    is_scrapable_url,
    scrape_url_content,
)


def _mock_async_client(response: Mock):
    mock_client = Mock()
    mock_client.stream.return_value = Mock(
        __aenter__=AsyncMock(return_value=response), __aexit__=AsyncMock(return_value=False)
    )

    mock_client_class = Mock()
    mock_client_class.return_value = Mock(
        __aenter__=AsyncMock(return_value=mock_client), __aexit__=AsyncMock(return_value=False)
    )
    return mock_client_class, mock_client


def _aiter_bytes(chunks: list[bytes]):
    async def _gen():
        for chunk in chunks:
            yield chunk

    return _gen()


class TestWebScrapingValidation:
    """Test URL validation for web scraping."""

    @pytest.mark.asyncio
    async def test_is_scrapable_url_valid_http(self):
        """Test valid HTTP URLs."""
        assert await is_scrapable_url("http://example.com")
        assert await is_scrapable_url("https://example.com")
        assert await is_scrapable_url("https://github.com/user/repo/pull/123")

    @pytest.mark.asyncio
    async def test_is_scrapable_url_invalid_scheme(self):
        """Test invalid URL schemes."""
        assert not await is_scrapable_url("ftp://example.com")
        assert not await is_scrapable_url("file:///path/to/file")
        assert not await is_scrapable_url("mailto:user@example.com")

    @pytest.mark.asyncio
    async def test_is_scrapable_url_invalid_format(self):
        """Test malformed URLs."""
        assert not await is_scrapable_url("not-a-url")
        assert not await is_scrapable_url("")
        assert not await is_scrapable_url("://missing-scheme")

    @pytest.mark.asyncio
    async def test_is_scrapable_url_skip_file_types(self):
        """Test that certain file types are skipped."""
        assert not await is_scrapable_url("https://example.com/file.pdf")
        assert not await is_scrapable_url("https://example.com/document.doc")
        assert not await is_scrapable_url("https://example.com/archive.zip")
        assert not await is_scrapable_url("https://example.com/data.xlsx")


class TestTextCleaning:
    """Test text cleaning functionality."""

    def test_clean_text_whitespace(self):
        """Test whitespace normalization."""
        text = "  Multiple   spaces    and\n\n\n\nmultiple\nlines  "
        expected = "Multiple spaces and\n\nmultiple lines"
        assert _clean_text(text) == expected

    def test_clean_text_web_artifacts(self):
        """Test removal of common web artifacts."""
        text = "Skip to content Main content here Cookie policy"
        expected = "Main content here policy"
        assert _clean_text(text) == expected

    def test_clean_text_empty(self):
        """Test handling of empty text."""
        assert _clean_text("") == ""
        assert _clean_text("   ") == ""
        assert _clean_text(None) == ""


class TestContentExtraction:
    """Test content extraction from HTML."""

    def test_extract_content_with_title(self):
        """Test extraction with page title."""
        from bs4 import BeautifulSoup

        html = (
            "<html><head><title>Test Page</title></head><body><main>"
            "This is a much longer piece of content that should meet the minimum "
            "character threshold for main content extraction. It needs to be at least "
            "100 characters long to be considered substantial content.</main></body></html>"
        )
        soup = BeautifulSoup(html, "html.parser")
        result = _extract_content(soup)
        assert "Title: Test Page" in result
        # The main content should be extracted since it's substantial (>100 chars)
        assert "Main content:" in result

    def test_extract_content_with_meta_description(self):
        """Test extraction with meta description."""
        from bs4 import BeautifulSoup

        html = """
        <html>
        <head>
            <title>Test</title>
            <meta name="description" content="Test description">
        </head>
        <body><main>Content</main></body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = _extract_content(soup)
        assert "Description: Test description" in result

    def test_extract_content_fallback_to_body(self):
        """Test fallback to body content when no main content found."""
        from bs4 import BeautifulSoup

        html = "<html><head><title>Test</title></head><body>Body content here</body></html>"
        soup = BeautifulSoup(html, "html.parser")
        result = _extract_content(soup)
        assert "Page content: Body content here" in result

    def test_extract_content_removes_navigation(self):
        """Test that navigation elements are removed."""
        from bs4 import BeautifulSoup

        html = """
        <html>
        <body>
            <nav>Navigation content</nav>
            <main>This is a much longer piece of content that should meet the minimum
            character threshold for main content extraction. It needs to be at least
            100 characters long to be considered substantial content.</main>
            <footer>Footer content</footer>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = _extract_content(soup)
        assert "Navigation content" not in result
        assert "Footer content" not in result
        # The main content should be extracted since it's substantial (>100 chars)
        assert "Main content:" in result


class TestWebScraping:
    """Test web scraping functionality."""

    @pytest.mark.asyncio
    async def test_scrape_url_content_success(self):
        """Test successful URL scraping."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {
            "content-length": "1000",
            "content-type": "text/html; charset=utf-8",
        }
        mock_response.raise_for_status.return_value = None
        mock_response.aiter_bytes = Mock(
            return_value=_aiter_bytes(
                [
                    b"<html><head><title>Test Page</title></head>",
                    b"<body><main>Test content</main></body></html>",
                ]
            )
        )

        mock_client_class, _mock_client = _mock_async_client(mock_response)

        with patch("src.web_scraper.httpx.AsyncClient", mock_client_class):

            result = await scrape_url_content("https://example.com")

        assert result is not None
        assert "Title: Test Page" in result
        # "Test content" is only 12 chars, so it won't meet the 100 char threshold
        # The test should fall back to body content extraction
        assert "Page content:" in result

    @pytest.mark.asyncio
    async def test_scrape_url_content_timeout(self):
        """Test handling of request timeout."""
        with patch("src.web_scraper.asyncio.timeout", side_effect=TimeoutError("Timeout")):
            result = await scrape_url_content("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_url_content_asyncio_timeout_context(self):
        """Test handling of asyncio timeout using the new async timeout context."""

        # Patch asyncio.timeout to raise TimeoutError when entered
        class DummyTimeout:
            async def __aenter__(self):
                msg = "async timeout"
                raise TimeoutError(msg)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch("src.web_scraper.asyncio.timeout", return_value=DummyTimeout()):
            result = await scrape_url_content("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_url_content_connection_error(self):
        """Test handling of connection errors."""
        mock_stream = Mock()
        mock_stream.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = Mock()
        mock_client.stream.return_value = mock_stream
        mock_client_class = Mock()
        mock_client_class.return_value = Mock(
            __aenter__=AsyncMock(return_value=mock_client),
            __aexit__=AsyncMock(return_value=False),
        )

        with patch("src.web_scraper.httpx.AsyncClient", mock_client_class):

            result = await scrape_url_content("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_url_content_http_error(self):
        """Test handling of HTTP errors."""
        mock_response = Mock()
        mock_response.status_code = 404
        http_error = httpx.HTTPStatusError("404 Not Found", request=Mock(), response=mock_response)
        mock_response.raise_for_status.side_effect = http_error

        mock_client_class, _mock_client = _mock_async_client(mock_response)

        with patch("src.web_scraper.httpx.AsyncClient", mock_client_class):

            result = await scrape_url_content("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_url_content_invalid_url(self):
        """Test handling of invalid URLs."""
        result = await scrape_url_content("not-a-url")
        assert result is None

        result = await scrape_url_content("ftp://example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_url_content_content_too_large(self):
        """Test handling of content that's too large."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-length": "1000000"}  # 1MB
        mock_response.raise_for_status.return_value = None

        mock_client_class, _mock_client = _mock_async_client(mock_response)

        with patch("src.web_scraper.httpx.AsyncClient", mock_client_class):

            result = await scrape_url_content("https://example.com", max_content_length=50000)

        # The content-length check should prevent downloading of large content
        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_url_content_with_logger(self):
        """Test scraping with custom logger."""
        mock_logger = Mock(spec=logging.Logger)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {
            "content-length": "1000",
            "content-type": "text/html; charset=utf-8",
        }
        mock_response.raise_for_status.return_value = None
        mock_response.aiter_bytes = Mock(
            return_value=_aiter_bytes(
                [
                    b"<html><head><title>Test</title></head><body>Content</body></html>",
                ]
            )
        )

        mock_client_class, _mock_client = _mock_async_client(mock_response)

        with patch("src.web_scraper.httpx.AsyncClient", mock_client_class):

            result = await scrape_url_content("https://example.com", logger=mock_logger)

        assert result is not None
        mock_logger.info.assert_called()
        mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_scrape_url_content_truncation(self):
        """Test content truncation when too long."""
        large_content = "<html><body>" + "A" * 60000 + "</body></html>"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {
            "content-length": str(len(large_content)),
            "content-type": "text/html; charset=utf-8",
        }
        mock_response.raise_for_status.return_value = None
        mock_response.aiter_bytes = Mock(return_value=_aiter_bytes([large_content.encode()]))

        mock_client_class, _mock_client = _mock_async_client(mock_response)

        with patch("src.web_scraper.httpx.AsyncClient", mock_client_class):

            result = await scrape_url_content("https://example.com", max_content_length=1000)

        assert result is not None
        assert len(result) <= 1050  # Allow for truncation message
        assert "[Content truncated due to length]" in result

    @pytest.mark.asyncio
    async def test_scrape_url_content_non_html_does_not_retry(self):
        """Ensure non-HTML responses stop the retry loop."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {
            "content-length": "1000",
            "content-type": "application/json",
        }
        mock_response.raise_for_status.return_value = None
        mock_response.aiter_bytes = Mock(return_value=_aiter_bytes([b"{}"]))

        mock_client_class, mock_client = _mock_async_client(mock_response)

        with patch("src.web_scraper.httpx.AsyncClient", mock_client_class):

            result = await scrape_url_content("https://example.com/data")

        assert result is None
        mock_client.stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_scrape_url_content_large_payload_closes_response(self):
        """Large payload checks should still close the HTTP response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {
            "content-length": str(MAX_DOWNLOAD_SIZE + 1),
            "content-type": "text/html",
        }
        mock_response.raise_for_status.return_value = None
        mock_response.aiter_bytes = Mock(return_value=_aiter_bytes([b"x"]))

        mock_client_class, mock_client = _mock_async_client(mock_response)

        with patch("src.web_scraper.httpx.AsyncClient", mock_client_class):

            result = await scrape_url_content("https://example.com/large")

        assert result is None
        mock_client.stream.assert_called_once()


class TestWebScrapingIntegration:
    """Test integration of web scraping with existing systems."""

    def test_web_scraping_error_inheritance(self):
        """Test that web scraping exceptions inherit correctly."""
        assert issubclass(WebScrapingError, Exception)

    @pytest.mark.asyncio
    async def test_scrape_url_content_empty_response(self):
        """Test handling of empty HTTP response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.raise_for_status.return_value = None
        mock_response.aiter_bytes = Mock(return_value=_aiter_bytes([b""]))

        mock_client_class, _mock_client = _mock_async_client(mock_response)

        with patch("src.web_scraper.httpx.AsyncClient", mock_client_class):

            result = await scrape_url_content("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_url_content_malformed_html(self):
        """Test handling of malformed HTML."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {
            "content-length": "100",
            "content-type": "text/html; charset=utf-8",
        }
        mock_response.raise_for_status.return_value = None
        mock_response.aiter_bytes = Mock(
            return_value=_aiter_bytes([b"<html><head><title>Test</title>"])
        )  # Malformed

        mock_client_class, _mock_client = _mock_async_client(mock_response)

        with patch("src.web_scraper.httpx.AsyncClient", mock_client_class):

            result = await scrape_url_content("https://example.com")

        # BeautifulSoup should handle malformed HTML gracefully
        assert result is not None
        assert "Title: Test" in result
