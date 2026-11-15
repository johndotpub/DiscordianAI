"""Single source for provider identity, client construction, and health wiring.

The registry intentionally describes providers without importing their
adapters. Health checks, the breaker table, and the health server derive their
provider names from :data:`PROVIDERS`, so adding a provider does not require
editing three parallel literals.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from src.config import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PERPLEXITY_MODEL,
    OPENAI_VALID_MODELS,
    PERPLEXITY_MODELS,
    is_supported_openai_model,
)
from src.models import OpenAIConfig, PerplexityConfig

OPENAI_RESPONSE_DEGRADED_THRESHOLD_MS = 5000
OPENAI_RESPONSE_UNHEALTHY_THRESHOLD_MS = 10000
PERPLEXITY_RESPONSE_DEGRADED_THRESHOLD_MS = 8000
PERPLEXITY_RESPONSE_UNHEALTHY_THRESHOLD_MS = 15000

ClientFactory = Callable[..., Any]

_DEPS_KEYS = {"openai": "client"}


@dataclass(frozen=True)
class ProviderSpec:
    """Describe one provider's configuration, client, and shared wiring.

    Attributes:
        name: Stable provider identifier used for deps, breakers, and health.
        config_type: Frozen configuration dataclass for this provider.
        client_factory: Callable taking a connection-pool manager plus the
            credentials and base URL, returning an SDK-compatible client.
        health: Whether the provider participates in health checks.
        breaker: Whether the provider gets a shared circuit breaker.
        health_metadata: Fields used to construct the provider's health spec.
    """

    name: str
    config_type: type[Any]
    client_factory: ClientFactory
    health: bool = True
    breaker: bool = True
    health_metadata: Mapping[str, Any] = field(default_factory=dict)


def _openai_client_factory(
    pool: Any,
    api_key: str,
    base_url: str,
    http_client: Any = None,
) -> Any:
    """Build the OpenAI-compatible client through the connection-pool manager."""
    return pool.create_openai_client(api_key, base_url, http_client)


def _perplexity_client_factory(
    pool: Any,
    api_key: str,
    base_url: str,
    http_client: Any = None,
) -> Any:
    """Build the Perplexity client through the connection-pool manager."""
    return pool.create_perplexity_client(api_key, base_url, http_client)


PROVIDERS: Mapping[str, ProviderSpec] = MappingProxyType(
    {
        "openai": ProviderSpec(
            name="openai",
            config_type=OpenAIConfig,
            client_factory=_openai_client_factory,
            health_metadata={
                "display_name": "OpenAI",
                "client_key": "openai",
                "model_key": "GPT_MODEL",
                "default_model": DEFAULT_OPENAI_MODEL,
                "allowed_models": tuple(OPENAI_VALID_MODELS),
                "model_validator": is_supported_openai_model,
                "degraded_threshold_ms": OPENAI_RESPONSE_DEGRADED_THRESHOLD_MS,
                "unhealthy_threshold_ms": OPENAI_RESPONSE_UNHEALTHY_THRESHOLD_MS,
                "deprecated_model_limit": 5,
            },
        ),
        "perplexity": ProviderSpec(
            name="perplexity",
            config_type=PerplexityConfig,
            client_factory=_perplexity_client_factory,
            health_metadata={
                "display_name": "Perplexity",
                "client_key": "perplexity",
                "model_key": "PERPLEXITY_MODEL",
                "default_model": DEFAULT_PERPLEXITY_MODEL,
                "allowed_models": tuple(PERPLEXITY_MODELS),
                "degraded_threshold_ms": PERPLEXITY_RESPONSE_DEGRADED_THRESHOLD_MS,
                "unhealthy_threshold_ms": PERPLEXITY_RESPONSE_UNHEALTHY_THRESHOLD_MS,
                "versioned_client": True,
            },
        ),
    }
)


def provider_names() -> tuple[str, ...]:
    """Return every registered provider name in registry order."""
    return tuple(PROVIDERS)


def get(name: str) -> ProviderSpec:
    """Return one provider spec.

    Raises:
        KeyError: If ``name`` is not registered.
    """
    try:
        return PROVIDERS[name]
    except KeyError:
        msg = f"Unknown provider: {name}"
        raise KeyError(msg) from None


def client_deps_key(name: str) -> str:
    """Return the legacy dependency-container key for a provider client."""
    return _DEPS_KEYS.get(name, f"{name}_client")
