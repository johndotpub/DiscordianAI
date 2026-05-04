"""Tests for connection pooling functionality."""

from unittest.mock import AsyncMock, Mock, patch

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
                max_retries=0,
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
                max_retries=0,
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


class TestPoolMetrics:
    """Test connection pool metrics and lifecycle tracking."""

    def test_get_pool_metrics_empty(self):
        """get_pool_metrics returns empty dict when no clients are tracked."""
        manager = ConnectionPoolManager()
        metrics = manager.get_pool_metrics()
        assert metrics == {}

    @patch("src.connection_pool.httpx.AsyncClient")
    def test_get_pool_metrics_tracks_client(self, mock_client):
        """get_pool_metrics includes client info after creation."""
        mock_instance = Mock(spec=[])  # empty spec avoids hasattr false positives
        mock_instance.is_closed = False
        mock_client.return_value = mock_instance

        manager = ConnectionPoolManager()
        manager.create_http_client("openai")

        metrics = manager.get_pool_metrics()
        assert "openai" in metrics
        assert metrics["openai"]["max_connections"] == 50
        assert metrics["openai"]["max_keepalive"] == 10
        assert metrics["openai"]["status"] == "active"

    @patch("src.connection_pool.httpx.AsyncClient")
    def test_get_pool_metrics_closed_client(self, mock_client):
        """get_pool_metrics reports closed clients correctly."""
        mock_instance = Mock(spec=["is_closed"])
        mock_instance.is_closed = True
        mock_client.return_value = mock_instance

        manager = ConnectionPoolManager()
        manager.create_http_client("openai")

        metrics = manager.get_pool_metrics()
        assert metrics["openai"]["status"] == "closed"

    @patch("src.connection_pool.httpx.AsyncClient")
    def test_get_pool_metrics_uptime(self, mock_client):
        """get_pool_metrics includes uptime_seconds for tracked clients."""
        mock_instance = Mock(spec=[])
        mock_instance.is_closed = False
        mock_client.return_value = mock_instance

        manager = ConnectionPoolManager()
        manager.create_http_client("openai")

        metrics = manager.get_pool_metrics()
        assert "uptime_seconds" in metrics["openai"]
        assert metrics["openai"]["uptime_seconds"] >= 0

    def test_check_pool_health_none_client(self):
        """check_pool_health returns unavailable when client is None."""
        manager = ConnectionPoolManager()
        result = manager.check_pool_health(None)
        assert result["status"] == "unavailable"

    def test_check_pool_health_closed_client(self):
        """check_pool_health returns unhealthy when client is closed."""
        mock_client = Mock(spec=["is_closed"])
        mock_client.is_closed = True
        manager = ConnectionPoolManager()
        result = manager.check_pool_health(mock_client)
        assert result["status"] == "unhealthy"

    def test_check_pool_health_healthy_client(self):
        """check_pool_health returns healthy for active client."""
        mock_client = Mock(spec=["is_closed"])
        mock_client.is_closed = False
        manager = ConnectionPoolManager()
        result = manager.check_pool_health(mock_client)
        assert result["status"] == "healthy"

    def test_check_pool_health_with_transport(self):
        """check_pool_health extracts pool stats from transport internals."""
        mock_pool = Mock(spec=["_connections", "_max_connections"])
        mock_pool._connections = [Mock(), Mock()]
        mock_pool._max_connections = 50

        mock_transport = Mock(spec=["_pool"])
        mock_transport._pool = mock_pool

        mock_client = Mock(spec=["is_closed", "_transport"])
        mock_client.is_closed = False
        mock_client._transport = mock_transport

        manager = ConnectionPoolManager()
        result = manager.check_pool_health(mock_client)
        assert result["status"] == "healthy"
        assert result["active_connections"] == 2
        assert result["max_connections"] == 50

    def test_check_pool_health_attribute_error(self):
        """check_pool_health handles unexpected AttributeError gracefully."""
        mock_client = Mock(spec=["is_closed"])
        mock_client.is_closed = False
        del mock_client._transport

        attr_err = AttributeError("unexpected")

        def raise_attr_error(*_args, **_kwargs):
            raise attr_err

        manager = ConnectionPoolManager()
        with patch("src.connection_pool.hasattr", side_effect=raise_attr_error):
            result = manager.check_pool_health(mock_client)
        assert result["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_close_http_client_success(self):
        """close_http_client closes a client successfully."""
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()
        manager = ConnectionPoolManager()
        await manager.close_http_client(mock_client)
        mock_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_http_client_error(self):
        """close_http_client logs warning on close error."""
        mock_client = AsyncMock()
        mock_client.aclose.side_effect = OSError("connection reset")
        manager = ConnectionPoolManager()
        await manager.close_http_client(mock_client)

    @pytest.mark.asyncio
    async def test_close_all(self):
        """close_all closes all tracked HTTP clients."""
        mock_client1 = AsyncMock()
        mock_client2 = AsyncMock()
        manager = ConnectionPoolManager()
        manager._clients = {"openai": mock_client1, "perplexity": mock_client2}
        await manager.close_all()
        mock_client1.aclose.assert_awaited_once()
        mock_client2.aclose.assert_awaited_once()
        assert manager._clients["openai"] is None
        assert manager._clients["perplexity"] is None

    @pytest.mark.asyncio
    async def test_close_all_handles_error(self):
        """close_all logs warning but continues on client close error."""
        mock_client1 = AsyncMock()
        mock_client1.aclose.side_effect = OSError("fail")
        mock_client2 = AsyncMock()
        manager = ConnectionPoolManager()
        manager._clients = {"openai": mock_client1, "perplexity": mock_client2}
        await manager.close_all()
        mock_client2.aclose.assert_awaited_once()
        assert manager._clients["openai"] is None

    def test_get_pool_metrics_unavailable_client(self):
        """get_pool_metrics reports unavailable when client is None in tracked dict."""
        manager = ConnectionPoolManager()
        manager._clients = {"openai": None}
        manager._creation_times = {"openai": 0.0}
        metrics = manager.get_pool_metrics()
        assert metrics["openai"]["status"] == "unavailable"
