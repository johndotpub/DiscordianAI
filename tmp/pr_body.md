## [0.2.9.5] - 2026-02-28

### Added ✨
- **Smart Routing Overhaul** ✨: Comprehensive improvements to `src/smart_orchestrator.py` and `src/config.py` to better classify queries and route between OpenAI and Perplexity. Key capabilities:
  - Routing-only Discord markup sanitization to avoid mutating history, cache keys, logs, or API payloads.
  - Persona-agnostic OpenAI web-inability detection (regex patterns) to automatically reroute responses that state they "can't browse" or "don't have access to the internet".
  - Explicit `SEARCH_INTENT_PATTERNS` expanded to capture phrases like "the web", "the internet", "search online", and related user intents.
  - Routing telemetry helper that surfaces the trigger labels used for routing decisions (logged for observability).

### Fixed 🔧
- **Bidirectional Fallbacks** 🔁: Implemented safe fallback chaining and degraded responses so both directions now fall back appropriately: Perplexity→OpenAI and OpenAI→Perplexity with clear logging and a final degraded response if both fail.
- **Perplexity History Persistence** 🧾: Ensure Perplexity user messages are persisted in conversation history only after a successful Perplexity response (parity with OpenAI) to avoid storing failed/timed-out turns.
- **Time-sensitivity False Positives** ⚠️: Removed overly-broad standalone tokens (e.g., `\\bnow\\b`) and tightened `TIME_SENSITIVITY_PATTERNS` to reduce false positives.
- **Entity & Factual Pattern Tightening** 🔎: Narrowed entity detection (proper names, stock tickers) to reduce noisy web-routing from short/all-caps tokens.

### Changed 🔁
- **Docs & Diagrams** 📝: Updated Mermaid diagrams and `docs/HybridMode.md`, `docs/Architecture.md`, and README references to reflect the new routing flow and fallback behavior.
- **Docstrings & Developer Guidance** 📚: Added Google-style docstrings for touched public functions and updated `.github/copilot-instructions.md` with the enforced test/lint sequence and Python 3.12 guidance.
- **CI / Docker** 🐳: Aligned CI and Docker to Python 3.12: `Dockerfile` base image bumped to `python:3.12-slim-bookworm`, `pyproject.toml` `requires-python` set to `>=3.12`, and GitHub Actions primary CI now requires Python 3.12 (`.github/workflows/ci.yml`).

### Tests ✅
- Added and updated unit tests covering routing sanitization, OpenAI web-inability reroute, search-intent recognition, follow-up/conversational detection, entity pattern tightening, Perplexity persistence behavior, and routing trigger logging assertions.
- Full test run: `tox -e py312` — **583 passed**, coverage **86.36%** (threshold 84%).

### Notes ⚠️
- No user-facing API changes to bot commands. Breaking change for contributors/CI: development and CI now target Python 3.12; update local environments accordingly.

### Breaking Change ❗️🐍
- **Dropped support for Python 3.10 and 3.11**: This release requires **Python 3.12 or newer**. CI, Docker, linters, and packaging have been updated to target `py312` as the minimum supported interpreter. If you're running this project locally on 3.10/3.11, please upgrade your interpreter or use a compatible environment. Update any deployment runners and CI configurations accordingly.

