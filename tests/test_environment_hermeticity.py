"""Guard against provider settings leaking in from the host shell."""

import os

PROVIDER_PREFIXES = ("OLLAMA_", "OPENAI_", "PERPLEXITY_", "ROUTER_")


def test_provider_and_router_variables_are_removed_before_each_test():
    """No test may depend on a provider key that happens to be exported."""
    inherited = sorted(
        name
        for name in os.environ
        if name.startswith(PROVIDER_PREFIXES) or name == "DISCORD_TOKEN"
    )

    assert not inherited, f"host variables reached a test: {inherited}"
