"""Provider-aware chat payload parameters."""

import pytest

from src.openai_processing import _build_openai_api_params, _provider_family

OLLAMA_BASE_URLS = [
    "https://ollama.com/v1/",
    "http://localhost:11434/v1/",
    "http://127.0.0.1:11434/v1/",
]
OPENAI_BASE_URL = "https://api.openai.com/v1/"


def _params(base_url: str, reasoning_effort: str | None = "high") -> dict:
    return _build_openai_api_params(
        "test-model",
        "You are a helpful assistant.",
        "Hello",
        1000,
        reasoning_effort=reasoning_effort,
        base_url=base_url,
    )


@pytest.mark.parametrize("base_url", OLLAMA_BASE_URLS)
def test_ollama_family_sends_max_tokens(base_url: str) -> None:
    """Ollama-compatible hosts receive max_tokens, not max_completion_tokens."""
    params = _params(base_url)

    assert params["max_tokens"] == 1000
    assert "max_completion_tokens" not in params
    assert params["reasoning_effort"] == "high"


def test_openai_family_sends_max_completion_tokens() -> None:
    """api.openai.com uses max_completion_tokens, not max_tokens."""
    params = _params(OPENAI_BASE_URL)

    assert params["max_completion_tokens"] == 1000
    assert "max_tokens" not in params
    assert params["reasoning_effort"] == "high"


@pytest.mark.parametrize("base_url", [*OLLAMA_BASE_URLS, OPENAI_BASE_URL])
@pytest.mark.parametrize("reasoning_effort", ["", None])
def test_empty_reasoning_effort_is_omitted(base_url: str, reasoning_effort) -> None:
    """An empty reasoning effort must not reach either provider."""
    params = _params(base_url, reasoning_effort=reasoning_effort)

    assert "reasoning_effort" not in params


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://ollama.com/v1/", "ollama"),
        ("https://api.ollama.com/v1/", "ollama"),
        ("http://localhost:11434/v1/", "ollama"),
        ("http://127.0.0.1:11434/v1/", "ollama"),
        (OPENAI_BASE_URL, "openai"),
        ("", "openai"),
    ],
)
def test_provider_family_from_base_url(base_url: str, expected: str) -> None:
    """The family follows the host, including any port on local hosts."""
    assert _provider_family(base_url) == expected
