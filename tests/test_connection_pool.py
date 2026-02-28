"""Tests for connection pooling functionality."""

from unittest.mock import Mock, patch

import pytest

from src.connection_pool import ConnectionPoolManager, get_connection_pool_manager


class TestConnectionPoolManager:
    """Test ConnectionPoolManager functionality."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        manager = ConnectionPoolManager()

        assert manager.openai_max_connections == 50
        assert manager.openai_max_keepalive == 10
        assert manager.perplexity_max_connections == 30
        assert manager.perplexity_max_keepalive == 5
        assert manager._logger is not None

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        manager = ConnectionPoolManager(
            openai_max_connections=100,
            openai_max_keepalive=20,
            perplexity_max_connections=60,
            perplexity_max_keepalive=15,
        )

        assert manager.openai_max_connections == 100
        assert manager.openai_max_keepalive == 20
        assert manager.perplexity_max_connections == 60
        assert manager.perplexity_max_keepalive == 15

    @patch("src.connection_pool.httpx.AsyncClient")
    def test_create_http_client_openai_with_http2(self, mock_client):
        """Test HTTP client creation for OpenAI with HTTP/2 support."""
        manager = ConnectionPoolManager()
        mock_instance = Mock()
        mock_client.return_value = mock_instance

        result = manager.create_http_client("openai")

        assert result == mock_instance
        mock_client.assert_called_once()
        call_args = mock_client.call_args
        assert call_args[1]["http2"] is True
        assert call_args[1]["follow_redirects"] is True

    @patch("src.connection_pool.httpx.AsyncClient")
    def test_create_http_client_perplexity_with_http2(self, mock_client):
        """Test HTTP client creation for Perplexity with HTTP/2 support."""
        manager = ConnectionPoolManager()
        mock_instance = Mock()
        mock_client.return_value = mock_instance

        result = manager.create_http_client("perplexity")

        assert result == mock_instance
        mock_client.assert_called_once()
        call_args = mock_client.call_args
        assert call_args[1]["http2"] is True
        assert call_args[1]["follow_redirects"] is True

    @patch("src.connection_pool.httpx.AsyncClient")
    def test_create_http_client_http2_fallback(self, mock_client):
        """Test HTTP/2 fallback when h2 package is missing."""
        manager = ConnectionPoolManager()

        # First call fails with ImportError, second succeeds
        successful_mock = Mock()
        mock_client.side_effect = [
            ImportError("Using http2=True, but the 'h2' package is not installed"),
            successful_mock,
        ]

        with patch.object(manager._logger, "warning") as mock_warning:
            result = manager.create_http_client("openai")

            # Should have been called twice (once fails, once succeeds)
            assert mock_client.call_count == 2
            assert result == successful_mock  # Verify we got the second (successful) client

            # First call should have http2=True, second should have http2=False
            first_call = mock_client.call_args_list[0]
            second_call = mock_client.call_args_list[1]

            assert first_call[1]["http2"] is True
            assert second_call[1]["http2"] is False

            # Should log a warning about HTTP/2 fallback
            mock_warning.assert_called_once()
            assert "HTTP/2 not available" in mock_warning.call_args[0][0]

    @patch("src.connection_pool.httpx.AsyncClient")
    def test_create_http_client_other_import_error(self, mock_client):
        """Test that other ImportErrors are not caught."""
        manager = ConnectionPoolManager()
        mock_client.side_effect = ImportError("Some other import error")

        with pytest.raises(ImportError, match="Some other import error"):
            manager.create_http_client("openai")

    @patch("src.connection_pool.httpx.AsyncClient")
    def test_create_openai_client(self, mock_http_client):
        """Test OpenAI client creation."""
        manager = ConnectionPoolManager()
        mock_http_instance = Mock()
        mock_http_client.return_value = mock_http_instance

        with patch("src.connection_pool.AsyncOpenAI") as mock_openai:
            mock_openai_instance = Mock()
            mock_openai.return_value = mock_openai_instance

            result = manager.create_openai_client(
                api_key="test-key",
                base_url="https://api.openai.com/v1/",
            )

            assert result == mock_openai_instance
            mock_openai.assert_called_once_with(
                api_key="test-key",
                base_url="https://api.openai.com/v1/",
                http_client=mock_http_instance,
            )

    @patch("src.connection_pool.httpx.AsyncClient")
    def test_create_perplexity_client(self, mock_http_client):
        """Test Perplexity client creation."""
        manager = ConnectionPoolManager()
        mock_http_instance = Mock()
        mock_http_client.return_value = mock_http_instance

        with patch("src.connection_pool.AsyncOpenAI") as mock_openai:
            mock_openai_instance = Mock()
            mock_openai.return_value = mock_openai_instance

            result = manager.create_perplexity_client(
                api_key="test-key",
                base_url="https://api.perplexity.ai",
            )

            assert result == mock_openai_instance
            mock_openai.assert_called_once_with(
                api_key="test-key",
                base_url="https://api.perplexity.ai",
                http_client=mock_http_instance,
            )


class TestGetConnectionPoolManager:
    """Test the get_connection_pool_manager factory function."""

    def test_get_manager_with_no_config(self):
        """Test getting manager with no configuration."""
        manager = get_connection_pool_manager()

        assert isinstance(manager, ConnectionPoolManager)
        assert manager.openai_max_connections == 50  # default

    def test_get_manager_with_config(self):
        """Test getting manager with configuration."""
        config = {
            "OPENAI_MAX_CONNECTIONS": 100,
            "OPENAI_MAX_KEEPALIVE": 20,
            "PERPLEXITY_MAX_CONNECTIONS": 60,
            "PERPLEXITY_MAX_KEEPALIVE": 15,
        }

        manager = get_connection_pool_manager(config)

        assert isinstance(manager, ConnectionPoolManager)
        assert manager.openai_max_connections == 100
        assert manager.openai_max_keepalive == 20
        assert manager.perplexity_max_connections == 60
        assert manager.perplexity_max_keepalive == 15

    def test_get_manager_with_partial_config(self):
        """Test getting manager with partial configuration."""
        config = {
            "OPENAI_MAX_CONNECTIONS": 75,
            # Missing other settings should use defaults
        }

        manager = get_connection_pool_manager(config)

        assert manager.openai_max_connections == 75
        assert manager.openai_max_keepalive == 10  # default
        assert manager.perplexity_max_connections == 30  # default
        assert manager.perplexity_max_keepalive == 5  # default
