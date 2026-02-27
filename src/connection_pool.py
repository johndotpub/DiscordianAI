"""Connection pooling utilities for API clients.

This module provides optimized HTTP connection pooling for OpenAI and Perplexity
API clients to reduce connection overhead and improve performance.
"""

import logging
from typing import Any

import httpx
from openai import AsyncOpenAI


class ConnectionPoolManager:
    """Manages HTTP connection pools for API clients.

    Provides optimized connection pooling settings for OpenAI and Perplexity
    API clients to reduce connection overhead and improve performance.
    """

    def __init__(
        self,
        openai_max_connections: int = 50,
        openai_max_keepalive: int = 10,
        perplexity_max_connections: int = 30,
        perplexity_max_keepalive: int = 5,
    ):
        """Initialize connection pool manager with API-specific settings.

        Args:
            openai_max_connections: Max connections for OpenAI API pool
            openai_max_keepalive: Max keepalive connections for OpenAI
            perplexity_max_connections: Max connections for Perplexity API pool
            perplexity_max_keepalive: Max keepalive connections for Perplexity
        """
        self.openai_max_connections = openai_max_connections
        self.openai_max_keepalive = openai_max_keepalive
        self.perplexity_max_connections = perplexity_max_connections
        self.perplexity_max_keepalive = perplexity_max_keepalive
        self._logger = logging.getLogger(__name__)

    def create_http_client(self, api_type: str = "openai") -> httpx.AsyncClient:
        """Create an optimized HTTP client with connection pooling.

        Args:
            api_type: Type of API ("openai" or "perplexity") for specific settings

        Returns:
            httpx.AsyncClient: Configured HTTP client with connection pooling
        """
        # Configure connection limits based on API type
        if api_type == "openai":
            max_connections = self.openai_max_connections
            max_keepalive = self.openai_max_keepalive
        else:  # perplexity
            max_connections = self.perplexity_max_connections
            max_keepalive = self.perplexity_max_keepalive

        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
        )

        # Configure timeouts
        timeout = httpx.Timeout(
            connect=10.0,  # Connection timeout
            read=30.0,  # Read timeout
            write=10.0,  # Write timeout
            pool=5.0,  # Pool timeout
        )

        # Try to enable HTTP/2 if available, fall back to HTTP/1.1
        try:
            client = httpx.AsyncClient(
                limits=limits,
                timeout=timeout,
                # Enable HTTP/2 for better performance
                http2=True,
                # Follow redirects
                follow_redirects=True,
            )
            self._logger.info("HTTP/2 enabled for %s connection pool", api_type)
        except ImportError as e:
            if "h2" in str(e):
                self._logger.warning(
                    "HTTP/2 not available for %s, falling back to HTTP/1.1. "
                    "Install httpx[http2] for better performance.",
                    api_type,
                )
                client = httpx.AsyncClient(
                    limits=limits,
                    timeout=timeout,
                    # HTTP/2 disabled due to missing dependencies
                    http2=False,
                    # Follow redirects
                    follow_redirects=True,
                )
            else:
                raise

        self._logger.debug(
            "Created HTTP client with connection pool: "
            "max_connections=%d, "
            "max_keepalive_connections=%d",
            max_connections,
            max_keepalive,
        )

        return client

    def create_openai_client(
        self,
        api_key: str,
        base_url: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> AsyncOpenAI:
        """Create an OpenAI client with optimized connection pooling.

        Args:
            api_key: OpenAI API key
            base_url: OpenAI API base URL
            http_client: Optional pre-configured HTTP client

        Returns:
            AsyncOpenAI: Configured OpenAI client
        """
        if http_client is None:
            http_client = self.create_http_client("openai")

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )

        self._logger.debug(
            "Created OpenAI client with connection pooling for %s "
            "(max_connections=%d, "
            "max_keepalive=%d)",
            base_url,
            self.openai_max_connections,
            self.openai_max_keepalive,
        )
        return client

    def create_perplexity_client(
        self,
        api_key: str,
        base_url: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> AsyncOpenAI:
        """Create a Perplexity client with optimized connection pooling.

        Args:
            api_key: Perplexity API key
            base_url: Perplexity API base URL
            http_client: Optional pre-configured HTTP client

        Returns:
            AsyncOpenAI: Configured Perplexity client
        """
        if http_client is None:
            http_client = self.create_http_client("perplexity")

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )

        self._logger.debug(
            "Created Perplexity client with connection pooling for %s "
            "(max_connections=%d, "
            "max_keepalive=%d)",
            base_url,
            self.perplexity_max_connections,
            self.perplexity_max_keepalive,
        )
        return client

    async def close_http_client(self, client: httpx.AsyncClient) -> None:
        """Close an HTTP client to free resources.

        Args:
            client: HTTP client to close
        """
        try:
            await client.aclose()
            self._logger.debug("HTTP client closed successfully")
        except (httpx.HTTPError, OSError) as e:
            self._logger.warning("Error closing HTTP client: %s", e)

    def check_pool_health(self, client: httpx.AsyncClient | None) -> dict[str, Any]:
        """Check health of connection pool.

        Args:
            client: HTTP client to check (optional)

        Returns:
            Dictionary with health status information
        """
        if client is None:
            return {"status": "unavailable", "reason": "Client not initialized"}

        try:
            # Check if client is closed
            if hasattr(client, "is_closed") and client.is_closed:
                return {"status": "unhealthy", "reason": "Client is closed"}

            # Get connection pool stats if available
            pool_info = {
                "status": "healthy",
                "http2_enabled": getattr(client, "_http2", False),
            }

            # Try to get connection pool statistics (accessing internal attrs is intentional)
            if hasattr(client, "_transport") and hasattr(
                client._transport,  # noqa: SLF001
                "_pool",
            ):
                pool = client._transport._pool  # noqa: SLF001
                if hasattr(pool, "_connections"):
                    pool_info["active_connections"] = len(pool._connections)  # noqa: SLF001
                if hasattr(pool, "_max_connections"):
                    pool_info["max_connections"] = pool._max_connections  # noqa: SLF001

        except AttributeError as e:
            self._logger.warning("Error checking pool health: %s", e)
            return {"status": "unknown", "reason": str(e)}
        else:
            return pool_info

    async def close_all(self) -> None:
        """Close all HTTP clients managed by this pool manager."""
        # This would need to track clients if we want to close them all
        # For now, clients are managed by the OpenAI/Perplexity clients
        self._logger.info("Connection pool manager shutdown requested")


def get_connection_pool_manager(config: dict | None = None) -> ConnectionPoolManager:
    """Get a connection pool manager instance with optional configuration.

    Args:
        config: Optional configuration dictionary with connection pool settings

    Returns:
        ConnectionPoolManager: Configured connection pool manager
    """
    if config is None:
        # Use defaults if no config provided
        return ConnectionPoolManager()

    return ConnectionPoolManager(
        openai_max_connections=config.get("OPENAI_MAX_CONNECTIONS", 50),
        openai_max_keepalive=config.get("OPENAI_MAX_KEEPALIVE", 10),
        perplexity_max_connections=config.get("PERPLEXITY_MAX_CONNECTIONS", 30),
        perplexity_max_keepalive=config.get("PERPLEXITY_MAX_KEEPALIVE", 5),
    )
