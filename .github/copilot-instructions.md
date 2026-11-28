# Copilot / Codex Instructions

DiscordianAI is a Python 3.12 Discord bot. Read `AGENTS.md` for the full engineering
contract; this file is the short version.

## Providers
- Chat responses go to an OpenAI-compatible endpoint. Ollama Cloud
  (`https://ollama.com/v1/`) is the shipped default.
- Perplexity handles messages that need live web data and citations.
- Provider calls are wrapped by the module-owned circuit breaker and retry policy; do
  not call `chat.completions.create()` directly from a new path.

## Routing
- `src/routing/` is a deterministic gate, not a weighted score. There are no router
  weights or thresholds to tune, and `ROUTER_MODE=model` is not implemented.
- The gate answers one question: does this message need live web data? Explicit web or
  local instructions and URLs decide first; otherwise bearing cues decide, with at most
  one follow-up inheritance. See `docs/routing/DESIGN.md`.
- The orchestrator owns routing, provider selection, fallback, and the single history
  write. Providers and clients must not decide routes or record conversation turns.

## Caching
- The router's route decides whether a response is cacheable; the cache salt includes
  the route and provider. There is no cache-TTL configuration key.
- Cache and deduplication keys are scoped to the conversation plus the request content.

## Verification
- Run tests with `.venv/bin/python -m pytest -q`.
- Style gates are `black . --check` and `ruff check .`.
- The full ordered gate set is `bash scripts/preflight.sh`; coverage must stay at or
  above 84% (`tox -e py312` runs the coverage gate).

## Style
- `ruff` and `black` own formatting (Black line length 99, ruff targets `py312`).
- Use modern type syntax (`str | None`, `list[dict[str, str]]`), annotate public
  functions, and write Google-style docstrings.
- Put shared constants and defaults in `src/config.py`; do not duplicate literals.
- Use `httpx`/`asyncio` in async paths; never `requests` or `time.sleep()`.

## Tests
- Mock boundaries (Discord objects, HTTP clients), never the function under test.
- A bug fix needs a regression test that fails without the fix.
- Shared fixtures live in `tests/conftest.py`; state protocol limits as absolute
  numbers in new tests.

## Secrets
- Never commit secrets, API keys, or local configuration. A deployment-specific
  `config.ini` is local-only and must never be committed or used as an example.
- `config.ini.example` is the shipped template; keep it free of real credentials.
