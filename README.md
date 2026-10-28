[![CI](https://github.com/johndotpub/DiscordianAI/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/ci.yml)
[![CodeQL](https://github.com/johndotpub/DiscordianAI/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/codeql.yml)
[![codecov](https://codecov.io/github/johndotpub/DiscordianAI/graph/badge.svg?token=4WOMJ952A2)](https://codecov.io/github/johndotpub/DiscordianAI)
[![Security: pip-audit](https://img.shields.io/badge/security-pip--audit-blueviolet)](https://github.com/johndotpub/DiscordianAI/actions/workflows/ci.yml)

[![Python 3.12+](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/badge/linter-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://pre-commit.com/)

[![Discord.py](https://img.shields.io/badge/discord.py-2.7.1-5865F2.svg?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![OpenAI](https://img.shields.io/badge/OpenAI-API-412991.svg?logo=openai&logoColor=white)](https://openai.com/)
[![Perplexity](https://img.shields.io/badge/Perplexity-Sonar--Pro-20B2AA.svg)](https://www.perplexity.ai/)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](http://unlicense.org/)

[![GitHub release](https://img.shields.io/github/v/release/johndotpub/DiscordianAI)](https://github.com/johndotpub/DiscordianAI/releases)
[![GitHub stars](https://img.shields.io/github/stars/johndotpub/DiscordianAI)](https://github.com/johndotpub/DiscordianAI/stargazers)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker&logoColor=white)](https://github.com/johndotpub/DiscordianAI/pkgs/container/discordianai)
[![GitHub issues](https://img.shields.io/github/issues/johndotpub/DiscordianAI)](https://github.com/johndotpub/DiscordianAI/issues)

# DiscordianAI

DiscordianAI is a Discord bot that routes each message to OpenAI or Perplexity, keeps conversation history per conversation, and formats replies for Discord. `GPT_MODEL` defaults to `gpt-5-mini` and is sent as configured: an unknown model name produces a startup warning, not an allowlist rejection. `PERPLEXITY_MODEL` defaults to `sonar-pro`. The provider decides which model names are valid. See [docs/API-CONTRACT.md](docs/API-CONTRACT.md) for what is sent to each provider.

## What Makes It Different

- **Hybrid routing**: OpenAI handles reasoning and creative prompts; Perplexity Sonar handles current events and returns citations.
- **Conversation history**: History is keyed by guild channel (`g:<guild>:c:<channel>`) or DM (`dm:<user>`) and is sent to both providers. A thread keeps its own history, separate from its parent. A follow-up is routed to the provider that answered the previous turn when one is recorded.
- **Discord-native output**: Citation embeds, message splitting at Discord's 2000-character limit, and link-preview embed suppression when a response contains two or more links.
- **Operations**: Per-provider HTTP/2 connection pooling with HTTP/1.1 fallback, per-provider circuit breakers, and health checks after login plus HTTP endpoints that report observed provider and breaker state.
- **Single-source configuration**: `config.ini` or environment variables drive every mode. Startup validation stops on missing credentials, malformed URLs, and invalid limits, and warns about unknown model names.

## Operation Modes

| Mode | What it does | When the chosen provider fails |
|------|--------------|--------------------------------|
| 🧠 **Smart Hybrid** | Requires both clients. Routes each message using URL, search-intent, follow-up, time-sensitivity, factual, entity, and conversational checks. | If Perplexity is selected and fails, the bot tries OpenAI. If OpenAI is selected and fails or returns no content, the bot tries Perplexity. An OpenAI answer that says it cannot browse is rerouted to Perplexity; if that reroute fails, the original OpenAI answer is returned. If both fail, the bot sends an error notice. |
| 🤖 **OpenAI Only** | Requires only the OpenAI client. Every message goes to the configured OpenAI model. | The bot sends an error notice. It does not fall back to Perplexity. |
| 🔍 **Perplexity Only** | Requires only the Perplexity client. Every message goes to the configured Perplexity model and citations are formatted into embeds. | The bot sends an error notice. It does not fall back to OpenAI. |

## Quick Start

1. **Install Python 3.12 or newer** and create a virtual environment.
2. **Clone & install**: `pip install -e ".[dev]"`
3. **Copy config**: `cp config.ini.example config.ini`
4. **Set tokens** in `config.ini` (Discord, OpenAI, Perplexity as needed).
5. **Run the bot**: `python -m src.main --conf config.ini` (or the installed console script: `discordianai --conf config.ini`).
6. **Run tests** before shipping: `pytest` (coverage gate: 84% via tox/Codecov)

Logs go to stdout. The bot does not open `bot.log`; the deprecated `LOG_FILE` setting is ignored. `bot.log` exists only when `discordian.sh` in daemon mode or a process supervisor redirects stdout to it.

Need the full Discord bot creation walkthrough and environment prep? See [docs/Setup.md](docs/Setup.md).

### Running directly

```bash
python -m src.main --conf config.ini --folder /path/to/base/folder
```

- `--conf` points at the config file.
- `--folder` (optional) makes config paths relative to a base directory (useful for Docker or systemd units).
- Logs go to stdout. The redirect or supervisor creates the file, for example `python -m src.main --conf config.ini >> bot.log 2>&1`. The bot opens only stdout, and `LOG_FILE` is deprecated and ignored.
- The installed console script accepts the same arguments: `discordianai --conf config.ini`.

### Running with the launcher script

The included [discordian.sh](discordian.sh) script handles Python environment resolution, venv bootstrapping, and process management:

```bash
# Foreground (development)
./discordian.sh -c config.ini

# Daemon mode (cron, background)
./discordian.sh -d -c config.ini

# Specify project directory explicitly
./discordian.sh -d -c production.ini -f /opt/discordianai

# Install a systemd service (auto-detects paths)
./discordian.sh --install-systemd bot.ini
```

The launcher resolves Python in this order: pyenv → project-local `.venv` → shell venv → system `python3`. It creates a `.venv/` automatically if none exists. It also ensures the working directory is correct — no more `ModuleNotFoundError: No module named 'src'` when running from cron. In daemon mode it redirects stdout to `bot.log` and records the process ID in `.bot.pid`.

`--install-systemd` generates a complete systemd user unit from the config file name (e.g., `bot.ini` → `discordian-bot@bot.service`), writes it to `~/.config/systemd/user/`, enables it, and prints management commands. See [docs/Daemon.md](docs/Daemon.md) for both cron and systemd setup. The shipped logrotate fragment is [contrib/logrotate/discordianai](contrib/logrotate/discordianai); it uses `copytruncate` because the bot never reopens a log file it did not open.

## Configuration Essentials

| Key | Purpose |
|-----|---------|
| `DISCORD_TOKEN` | Bot authentication token from the Discord Developer Portal.
| `GPT_MODEL` | OpenAI model name sent as configured. Default `gpt-5-mini`; unknown names warn but do not block startup.
| `PERPLEXITY_MODEL` | Perplexity model name. Default `sonar-pro`; known names include `sonar`, `sonar-deep-research`, and `sonar-reasoning-pro`.
| `INPUT_TOKENS` / `OUTPUT_TOKENS` | Prompt budget and OpenAI completion cap. `OUTPUT_TOKENS` is sent as `max_completion_tokens` and includes reasoning tokens.
| `PERPLEXITY_OUTPUT_TOKENS` | Perplexity completion cap, sent as `max_tokens` (output only). Defaults to `OUTPUT_TOKENS`.
| `LOOKBACK_MESSAGES_FOR_CONSISTENCY` | How many recent messages to inspect when a follow-up inherits the previous provider.
| `CONVERSATION_TTL_SECONDS` | Idle seconds before a conversation and its lock are evicted (default 1800).
| `MAX_URLS_PER_MESSAGE` | Maximum URLs scraped from one message; extras are ignored (default 3).
| `MAX_TOTAL_SCRAPED_CHARS` | Maximum combined scraped text injected into one prompt (default 60000).
| `SCRAPE_DEADLINE_SECONDS` | Deadline for the scrape phase of one message, in seconds (default 20).
| `OPENAI_MAX_CONNECTIONS` / `PERPLEXITY_MAX_CONNECTIONS` | HTTP/2 pool connection limits for each API client.

### Channel Targeting

- `ALLOWED_CHANNELS` matches channel names case-insensitively (a leading `#` is ignored).
- `ALLOWED_CHANNEL_IDS` matches channel IDs and takes precedence when set.
- `ALLOWED_GUILDS` / `ALLOWED_GUILD_IDS` scope name matching to configured servers; without them, names resolve only in the first guild the bot joins.
- Threads are authorised by their parent channel's allowlist, but their conversation history uses the thread's own channel ID.
- Other bots are ignored unless their user ID is listed in `TRUSTED_BOT_IDS`.
- Prefer IDs for stable targeting across servers; names are handy for local testing.

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
- [src/smart_orchestrator.py](src/smart_orchestrator.py) routes by URL, search-intent, follow-up, time-sensitivity, factual, entity, and conversational patterns and owns provider selection and history writes.
- [src/message_processor.py](src/message_processor.py) builds the per-conversation history snapshot and request, calls the orchestrator, and sends the reply.
- [src/openai_processing.py](src/openai_processing.py) and [src/perplexity_processing.py](src/perplexity_processing.py) send only the model, messages, and provider completion cap; neither sends sampling parameters. Perplexity processing also handles scrape budgets and citation extraction.

### Discord User Experience
- [src/discord_embeds.py](src/discord_embeds.py) formats Perplexity citations into embed descriptions and truncates descriptions above the 4096-character hard limit to the 3840-character safe limit.
- [src/message_splitter.py](src/message_splitter.py) splits at 2000 characters, uses 3840 as the safe embed split target and 4096 as the hard embed limit, avoids splitting code blocks, and provides the link-count check used to suppress previews at two or more links.
- [src/message_router.py](src/message_router.py) handles mentions, DMs, channel and thread allowlists, trusted bots, and dispatch to the DM/channel processors.

### Reliability & Ops
- [src/connection_pool.py](src/connection_pool.py) creates HTTP/2 clients with 50/10 connections for OpenAI and 30/5 for Perplexity, falling back to HTTP/1.1 when `h2` is unavailable.
- [src/health_checks.py](src/health_checks.py) checks each configured provider after login; supported models are checked against the provider's model-list endpoint. [src/health_server.py](src/health_server.py) serves liveness/readiness and reports observed provider and breaker state.
- [src/api_validation.py](src/api_validation.py) rejects missing credentials, malformed URLs, and invalid limits, and warns about unknown model names. [src/error_handling.py](src/error_handling.py) classifies errors and owns the retry and circuit-breaker policy.

## Documentation Map

| Topic | Reference |
|-------|-----------|
| Engineering contract | [AGENTS.md](AGENTS.md)
| Provider request/response contract | [docs/API-CONTRACT.md](docs/API-CONTRACT.md)
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
pip install -e ".[dev]"

# Lint & format
ruff check --fix .
black .

# Run the targeted suites
pytest -q
pytest tests/test_smart_orchestrator_coverage.py
```

Run the full local gate with [scripts/preflight.sh](scripts/preflight.sh): `bash scripts/preflight.sh`. It runs Black, Ruff, pytest, the Sphinx build, and a wheel build.

Use `tox` for the CI matrix (`tox`, `tox -e py312`, `tox --parallel auto`, `tox -e audit`). CI runs Ruff, Black, pytest with coverage, pip-audit, and a wheel install smoke test; locally run `tox -e audit` to scan runtime + dev deps.

## Security Checklist

- Keep `config.ini` out of version control; copy from `config.ini.example` and set `chmod 600 config.ini` on servers.
- Prefer environment variables in production (`export DISCORD_TOKEN=...`).
- Rotate OpenAI (`sk-...`) and Perplexity (`pplx-...`) keys regularly; validators will reject malformed prefixes.
- Limit Discord bot permissions to the channels where it operates.
- Prefer `ALLOWED_CHANNEL_IDS` for precise channel targeting in shared or multi-server deployments.
- Scraped URLs are checked for loopback, private, link-local, CGNAT, and other non-global addresses, and every redirect hop is checked. HTTPS is not pinned to the vetted IP, so a DNS-rebinding window remains; see [docs/Security.md](docs/Security.md).
- Monitor logs for rate-limit bursts or scraping failures and adjust `RATE_LIMIT` / `RATE_LIMIT_PER` accordingly.

## Support & License

- Questions or feedback: [github@john.pub](mailto:github@john.pub)
- Issues and feature requests: open a GitHub issue.
- Licensed under the [Unlicense](LICENSE).
