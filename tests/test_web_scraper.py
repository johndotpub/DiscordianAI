"""Tests for web scraping functionality."""

import logging
from unittest.mock import Mock, patch

import pytest

from src.web_scraper import (
    ContentExtractionError,
    WebScrapingError,
    _clean_text,
    _extract_content,
    is_scrapable_url,
    scrape_url_content,
)


class TestWebScrapingValidation:
    """Test URL validation for web scraping."""

    def test_is_scrapable_url_valid_http(self):
        """Test valid HTTP URLs."""
        assert is_scrapable_url("http://example.com")
        assert is_scrapable_url("https://example.com")
        assert is_scrapable_url("https://github.com/user/repo/pull/123")

    def test_is_scrapable_url_invalid_scheme(self):
        """Test invalid URL schemes."""
        assert not is_scrapable_url("ftp://example.com")
        assert not is_scrapable_url("file:///path/to/file")
        assert not is_scrapable_url("mailto:user@example.com")

    def test_is_scrapable_url_invalid_format(self):
        """Test malformed URLs."""
        assert not is_scrapable_url("not-a-url")
        assert not is_scrapable_url("")
        assert not is_scrapable_url("://missing-scheme")

    def test_is_scrapable_url_skip_file_types(self):
        """Test that certain file types are skipped."""
        assert not is_scrapable_url("https://example.com/file.pdf")
        assert not is_scrapable_url("https://example.com/document.doc")
        assert not is_scrapable_url("https://example.com/archive.zip")
        assert not is_scrapable_url("https://example.com/data.xlsx")


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
        mock_response.iter_content.return_value = [
            b"<html><head><title>Test Page</title></head>",
            b"<body><main>Test content</main></body></html>",
        ]

        # Mock the session.get method since the function uses requests.Session()
        with patch("src.web_scraper.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_session.get.return_value = mock_response
            mock_session_class.return_value = mock_session

            result = await scrape_url_content("https://example.com")

        assert result is not None
        assert "Title: Test Page" in result
        # "Test content" is only 12 chars, so it won't meet the 100 char threshold
        # The test should fall back to body content extraction
        assert "Page content:" in result

    @pytest.mark.asyncio
    async def test_scrape_url_content_timeout(self):
        """Test handling of request timeout."""

        # Create a custom exception class for testing
        class TimeoutTestError(Exception):
            pass

        timeout_exception = TimeoutTestError("Timeout")

        # Mock the session.get method since the function uses requests.Session()
        with patch("src.web_scraper.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_session.get.side_effect = timeout_exception
            mock_session_class.return_value = mock_session

            result = await scrape_url_content("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_url_content_connection_error(self):
        """Test handling of connection errors."""

        # Create a custom exception class for testing
        class ConnectionTestError(Exception):
            pass

        connection_error = ConnectionTestError("Connection failed")

        # Mock the session.get method since the function uses requests.Session()
        with patch("src.web_scraper.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_session.get.side_effect = connection_error
            mock_session_class.return_value = mock_session

            result = await scrape_url_content("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_scrape_url_content_http_error(self):
        """Test handling of HTTP errors."""
        mock_response = Mock()
        mock_response.status_code = 404

        # Create a custom exception class for testing
        class HTTPError(Exception):
            def __init__(self, message, response=None):
                super().__init__(message)
                self.response = response

        http_error = HTTPError("404 Not Found", mock_response)

        # Mock the session.get method since the function uses requests.Session()
        with patch("src.web_scraper.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_session.get.side_effect = http_error
            mock_session_class.return_value = mock_session

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

        # Mock the session.get method since the function uses requests.Session()
        with patch("src.web_scraper.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_session.get.return_value = mock_response
            mock_session_class.return_value = mock_session

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
        mock_response.iter_content.return_value = [
            b"<html><head><title>Test</title></head><body>Content</body></html>",
        ]

        # Mock the session.get method since the function uses requests.Session()
        with patch("src.web_scraper.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_session.get.return_value = mock_response
            mock_session_class.return_value = mock_session

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
        mock_response.iter_content.return_value = [large_content.encode()]

        # Mock the session.get method since the function uses requests.Session()
        with patch("src.web_scraper.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_session.get.return_value = mock_response
            mock_session_class.return_value = mock_session

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
        mock_response.iter_content.return_value = [b"{}"]

        with patch("src.web_scraper.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_session.get.return_value = mock_response
            mock_session_class.return_value = mock_session

            result = await scrape_url_content("https://example.com/data")

        assert result is None
        mock_session.get.assert_called_once()


class TestWebScrapingIntegration:
    """Test integration of web scraping with existing systems."""

    def test_web_scraping_error_inheritance(self):
        """Test that web scraping exceptions inherit correctly."""
        assert issubclass(WebScrapingError, Exception)
        assert issubclass(ContentExtractionError, WebScrapingError)

    @pytest.mark.asyncio
    async def test_scrape_url_content_empty_response(self):
        """Test handling of empty HTTP response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.raise_for_status.return_value = None
        mock_response.iter_content.return_value = [b""]

        # Mock the session.get method since the function uses requests.Session()
        with patch("src.web_scraper.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_session.get.return_value = mock_response
            mock_session_class.return_value = mock_session

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
        mock_response.iter_content.return_value = [b"<html><head><title>Test</title>"]  # Malformed

        # Mock the session.get method since the function uses requests.Session()
        with patch("src.web_scraper.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_session.get.return_value = mock_response
            mock_session_class.return_value = mock_session

            result = await scrape_url_content("https://example.com")

        # BeautifulSoup should handle malformed HTML gracefully
        assert result is not None
        assert "Title: Test" in result
