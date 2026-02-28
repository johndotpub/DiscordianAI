[![CI](https://github.com/johndotpub/DiscordianAI/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/ci.yml)
[![CodeQL](https://github.com/johndotpub/DiscordianAI/actions/workflows/github-code-scanning/codeql/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/github-code-scanning/codeql)
[![codecov](https://codecov.io/github/johndotpub/DiscordianAI/graph/badge.svg?token=4WOMJ952A2)](https://codecov.io/github/johndotpub/DiscordianAI)
[![Security: pip-audit](https://img.shields.io/badge/security-pip--audit-blueviolet)](https://pypi.org/project/pip-audit/)

[![Tests: py312 required](https://img.shields.io/github/actions/workflow/status/johndotpub/DiscordianAI/ci.yml?branch=main&label=tests%20py312%20required&logo=githubactions)](https://github.com/johndotpub/DiscordianAI/actions/workflows/ci.yml)
[![Tests: py311 opt](https://img.shields.io/github/actions/workflow/status/johndotpub/DiscordianAI/ci.yml?branch=main&label=tests%20py311%20opt&logo=githubactions&color=94C973)](https://github.com/johndotpub/DiscordianAI/actions/workflows/ci.yml)
[![Tests: py310 opt](https://img.shields.io/github/actions/workflow/status/johndotpub/DiscordianAI/ci.yml?branch=main&label=tests%20py310%20opt&logo=githubactions&color=94C973)](https://github.com/johndotpub/DiscordianAI/actions/workflows/ci.yml)
[![Python 3.12 focus | 3.10+ support](https://img.shields.io/badge/python-3.12%20focus%20%7C%203.10%2B%20support-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://pre-commit.com/)

[![Discord.py](https://img.shields.io/badge/discord.py-2.6.4-5865F2.svg?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--5-412991.svg?logo=openai&logoColor=white)](https://openai.com/)
[![Perplexity](https://img.shields.io/badge/Perplexity-Sonar--Pro-20B2AA.svg)](https://www.perplexity.ai/)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](http://unlicense.org/)

[![GitHub release](https://img.shields.io/github/v/release/johndotpub/DiscordianAI)](https://github.com/johndotpub/DiscordianAI/releases)
[![GitHub stars](https://img.shields.io/github/stars/johndotpub/DiscordianAI)](https://github.com/johndotpub/DiscordianAI/stargazers)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker&logoColor=white)](https://github.com/johndotpub/DiscordianAI/pkgs/container/discordianai)
[![GitHub issues](https://img.shields.io/github/issues/johndotpub/DiscordianAI)](https://github.com/johndotpub/DiscordianAI/issues)

# DiscordianAI

DiscordianAI is a production-ready Discord bot that blends OpenAI GPT-5 frontier models with Perplexity Sonar-Pro web search. It focuses on conversation consistency, deterministic routing, and Discord-native formatting so answers stay contextual, accurate, and easy to read.

## What Makes It Different

- **Hybrid intelligence**: GPT-5 handles reasoning/creative prompts while Sonar-Pro covers current events with structured citations.
- **Conversation consistency**: Follow-up detector keeps a thread on the same AI service, preventing jarring context shifts.
- **Discord-first UX**: Citation-aware embeds, smart message splitting, and automatic embed suppression keep chats readable.
- **Operations minded**: HTTP/2 connection pooling, circuit breakers, and health checks keep long-running bots stable.
- **Single-source configuration**: `config.ini` drives every runtime mode, and validators catch unsupported parameters early.

## Operation Modes

| Mode | Description |
|------|-------------|
| 🧠 **Smart Hybrid** | Analyze each message, then route to GPT-5 or Sonar-Pro with follow-up consistency.
| 🤖 **OpenAI Only** | Force GPT-5 for every response; great for creative and coding-focused servers.
| 🔍 **Perplexity Only** | Force Sonar-Pro for every response; ideal for research or news-heavy servers.

## Quick Start

1. **Install Python 3.12 (preferred; 3.10/3.11 optional)** and create a virtual environment.
2. **Clone & install**: `pip install -e .[dev]`
3. **Copy config**: `cp config.ini.example config.ini`
4. **Set tokens** in `config.ini` (Discord, OpenAI, Perplexity as needed).
5. **Run the bot**: `python -m src.main --conf config.ini`
6. **Run tests** before shipping: `pytest` (coverage gate: 84% via tox/Codecov)

Need the full Discord bot creation walkthrough and environment prep? See [docs/Setup.md](docs/Setup.md).

### Running directly

```bash
python -m src.main --conf config.ini --folder /path/to/base/folder
```

- `--conf` points at the config file.
- `--folder` (optional) makes config/log paths relative to a base directory (useful for Docker or systemd units).

## Configuration Essentials

| Key | Purpose |
|-----|---------|
| `DISCORD_TOKEN` | Bot authentication token from the Discord Developer Portal.
| `GPT_MODEL` | GPT-5 series model (`gpt-5-mini`, `gpt-5`, `gpt-5-nano`, `gpt-5-chat`).
| `PERPLEXITY_MODEL` | Perplexity Sonar model (`sonar-pro` default, `sonar` fallback).
| `INPUT_TOKENS` / `OUTPUT_TOKENS` | Caps for prompt and completion tokens (GPT-5 uses `max_completion_tokens`).
| `LOOKBACK_MESSAGES_FOR_CONSISTENCY` | How many prior turns to inspect when enforcing AI service consistency.
| `OPENAI_MAX_CONNECTIONS` / `PERPLEXITY_MAX_CONNECTIONS` | HTTP/2 pooling limits for each API client.

### Minimal hybrid config

```ini
[Discord]
DISCORD_TOKEN=your_discord_bot_token

[Default]
OPENAI_API_KEY=sk-your-openai-key
OPENAI_API_URL=https://api.openai.com/v1/
GPT_MODEL=gpt-5-mini
PERPLEXITY_API_KEY=pplx-your-perplexity-key
PERPLEXITY_MODEL=sonar-pro
INPUT_TOKENS=120000
OUTPUT_TOKENS=8000
SYSTEM_MESSAGE=You are a helpful assistant with access to current web information.

[Limits]
RATE_LIMIT=10
RATE_LIMIT_PER=60
```

## Key Components

### AI Orchestration
- `smart_orchestrator.py` routes messages via semantic analysis, entity detection, and follow-up tracking.
- `message_processor.py` normalizes Discord input, calls the orchestrator, and records AI metadata for future turns.
- `openai_processing.py` and `perplexity_processing.py` build strictly supported API payloads (GPT-5 ignores temperature, Sonar-Pro sampling is managed server-side).

### Discord User Experience
- `discord_embeds.py` formats Perplexity citations into clean embeds with automatic suppression when multiple links exist.
- `message_splitter.py` enforces Discord limits (2000 / 3840 / 4096 chars) with code-block and citation awareness.
- `message_router.py` centralizes mention handling, DM routing, and rate-limit responses.

### Reliability & Ops
- `connection_pool.py` exposes tuned HTTP/2 clients (50/10 connections for OpenAI, 30/5 for Perplexity).
- `health_checks.py` verifies API reachability and validates GPT-5/Sonar configurations at startup.
- `api_validation.py` + `api_utils.py` guard against unsupported model strings and capture structured error metadata.

## Documentation Map

| Topic | Reference |
|-------|-----------|
| Setup & onboarding | [docs/Setup.md](docs/Setup.md)
| Architecture & flow | [docs/Architecture.md](docs/Architecture.md)
| Smart routing internals | [docs/HybridMode.md](docs/HybridMode.md)
| Configuration deep dive | [docs/Configuration.md](docs/Configuration.md)
| OpenAI usage | [docs/OpenAI.md](docs/OpenAI.md)
| Perplexity usage & citations | [docs/Perplexity.md](docs/Perplexity.md)
| Message splitting & embeds | [docs/MessageSplitting.md](docs/MessageSplitting.md), [docs/EmbedLimits.md](docs/EmbedLimits.md)
| Web scraping pipeline | [docs/WebScraping.md](docs/WebScraping.md)
| Connection pooling & HTTP/2 | [docs/ConnectionPooling.md](docs/ConnectionPooling.md)
| Docker & daemonization | [docs/Docker.md](docs/Docker.md), [docs/Daemon.md](docs/Daemon.md)
| Security & rate limiting | [docs/Security.md](docs/Security.md)
| Development workflow | [docs/Development.md](docs/Development.md)
| API parameter validation | [docs/API_Validation.md](docs/API_Validation.md)

## Development Workflow

```bash
# Install dev extras
pip install -e .[dev]

# Lint & format
ruff check --fix .
black .

# Run the targeted suites
pytest -q
pytest tests/test_smart_orchestrator_coverage.py
```

Use `tox` for the CI matrix (`tox`, `tox -e py310`, `tox --parallel auto`). CI runs Ruff, Black, pytest with coverage, and pip-audit.

## Security Checklist

- Keep `config.ini` out of version control; copy from `config.ini.example` and set `chmod 600 config.ini` on servers.
- Prefer environment variables in production (`export DISCORD_TOKEN=...`).
- Rotate OpenAI (`sk-...`) and Perplexity (`pplx-...`) keys regularly; validators will reject malformed prefixes.
- Limit Discord bot permissions to the channels where it operates.
- Monitor logs for rate-limit bursts or scraping failures and adjust `RATE_LIMIT` / `RATE_LIMIT_PER` accordingly.

## Support & License

- Questions or feedback: [github@john.pub](mailto:github@john.pub)
- Issues and feature requests: open a GitHub issue.
- Licensed under the [Unlicense](LICENSE).
