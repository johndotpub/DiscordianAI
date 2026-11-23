"""Single source for provider identity, client construction, and health wiring.

Adapter modules are imported lazily when an adapter is built, so loading the
registry stays cheap and cannot create an import cycle through the adapters.
Health checks, the breaker table, and the health server derive their provider
names from :data:`PROVIDERS`, so adding a provider does not require editing
three parallel literals.
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
        label: Display name used in logs and health output.
        api_key_key: Config key holding this provider's API key.
        base_url_key: Config key holding this provider's base URL.
        model_key: Config key holding this provider's model identifier.
        disabled_hint: Log suffix explaining what stops working without a key.
        config_type: Frozen configuration dataclass for this provider.
        client_factory: Callable taking a connection-pool manager plus the
            credentials and base URL, returning an SDK-compatible client.
        health: Whether the provider participates in health checks.
        breaker: Whether the provider gets a shared circuit breaker.
        health_metadata: Fields used to construct the provider's health spec.
    """

    name: str
    label: str
    api_key_key: str
    base_url_key: str
    model_key: str
    disabled_hint: str
    config_type: type[Any]
    client_factory: ClientFactory
    health: bool = True
    breaker: bool = True
    health_metadata: Mapping[str, Any] = field(default_factory=dict)

    def build_adapter(self, client: Any) -> Any:
        """Build this provider's adapter around ``client`` with default config."""
        if self.name == "openai":
            from .openai_chat import ChatCompletionsProvider  # noqa: PLC0415 - lazy import

            return ChatCompletionsProvider(client, self.config_type())
        if self.name == "perplexity":
            from .perplexity import AgentResponsesProvider  # noqa: PLC0415 - lazy import

            return AgentResponsesProvider(client, self.config_type())
        msg = f"No adapter is registered for provider {self.name!r}"
        raise KeyError(msg)


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
            label="OpenAI",
            api_key_key="OPENAI_API_KEY",
            base_url_key="OPENAI_API_URL",
            model_key="GPT_MODEL",
            disabled_hint="GPT models disabled",
            config_type=OpenAIConfig,
            client_factory=_openai_client_factory,
            health_metadata={
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
            label="Perplexity",
            api_key_key="PERPLEXITY_API_KEY",
            base_url_key="PERPLEXITY_API_URL",
            model_key="PERPLEXITY_MODEL",
            disabled_hint="web search disabled",
            config_type=PerplexityConfig,
            client_factory=_perplexity_client_factory,
            health_metadata={
                "default_model": DEFAULT_PERPLEXITY_MODEL,
                "allowed_models": tuple(PERPLEXITY_MODELS),
                "degraded_threshold_ms": PERPLEXITY_RESPONSE_DEGRADED_THRESHOLD_MS,
                "unhealthy_threshold_ms": PERPLEXITY_RESPONSE_UNHEALTHY_THRESHOLD_MS,
                "versioned_client": True,
            },
        ),
    }
)


def build_configured_clients(pool: Any, config: Mapping[str, Any], logger: Any) -> dict[str, Any]:
    """Build every provider client whose API key is configured.

    Args:
        pool: Connection-pool manager exposing each provider's client factory.
        config: Loaded configuration mapping.
        logger: Logger for one line per configured or skipped provider.

    Returns:
        A mapping from provider name to its SDK client. A provider whose key
        is missing is absent from the mapping.

    Raises:
        RuntimeError: If a configured provider's client cannot be constructed.
    """
    clients: dict[str, Any] = {}
    for name, spec in PROVIDERS.items():
        if not config.get(spec.api_key_key):
            logger.info("No %s API key provided; %s", spec.api_key_key, spec.disabled_hint)
            continue
        try:
            clients[name] = spec.client_factory(
                pool,
                config[spec.api_key_key],
                config[spec.base_url_key],
            )
        except Exception as exc:
            logger.exception("Failed to initialize %s client", spec.label)
            msg = f"{spec.label} client initialization failed"
            raise RuntimeError(msg) from exc
        logger.info(
            "%s client initialized with model %s (connection pooling enabled)",
            spec.label,
            config[spec.model_key],
        )
    return clients


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
