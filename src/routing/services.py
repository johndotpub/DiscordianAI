"""The single mapping between provider services and routes."""

ROUTE_BY_SERVICE: dict[str, str] = {"perplexity": "web", "openai": "local"}
SERVICE_BY_ROUTE: dict[str, str] = {route: service for service, route in ROUTE_BY_SERVICE.items()}
