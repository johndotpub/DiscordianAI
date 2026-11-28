# Security Best Practices

This document outlines security considerations and best practices for deploying and operating DiscordianAI.

## 🔐 API Key Management

### Storage

**Never commit API keys to version control.** Use one of these approaches:

1. **Environment Variables** (Recommended for production)
   ```bash
   export DISCORD_TOKEN="your_token_here"
   export OPENAI_API_KEY="sk-..."
   export PERPLEXITY_API_KEY="pplx-..."
   ```
   For containers, the shipped `docker-compose.yml` loads these from `.env` with
   `env_file: [.env]`. Compose's own `.env` file is only used for variable
   substitution, which is why the compose file injects it explicitly.

2. **Config File** (Development only)
   ```ini
   # config.ini - Add to .gitignore!
   [Discord]
   DISCORD_TOKEN=your_token_here
   
   [Default]
   OPENAI_API_KEY=sk-...
   PERPLEXITY_API_KEY=pplx-...
   ```
   
   **Important:** Restrict file permissions:
   ```bash
   chmod 600 config.ini
   ```

3. **Environment file for containers** (recommended for production)
   The shipped `docker-compose.yml` loads credentials from `.env` with
   `env_file: [.env]`. Create that file from the tracked template, keep it out of
   version control, and restrict its permissions:
   ```bash
   cp .env.example .env
   chmod 600 .env
   # Edit .env and set DISCORD_TOKEN plus the provider keys you use.
   ```
   The bot does not read Docker secret files, mounted secret paths, or any other
   secret-file mechanism. Credentials come only from `config.ini` and environment
   variables.

### Key Format Validation

DiscordianAI validates API key formats before use:

| Service | Expected Format | Example |
|---------|-----------------|---------|
| OpenAI-compatible | Any non-empty key is accepted; the shape is not checked and the provider rejects a wrong key at request time | `sk-abc123...` or an Ollama Cloud key |
| Perplexity | `pplx-` + at least 20 letters, digits, `-` or `_` | `pplx-xyz789...` |

A blank key disables that provider, and a whitespace-only value counts as blank in both the config file and the environment. A provider counts as configured when its key is non-empty, or when its base URL or model is set in the file or environment. A configured provider without a key stops startup even when the other provider has a key; to run only one provider, leave the other provider at its defaults or set its key blank. Any non-empty OpenAI-compatible key is accepted because the configured provider decides what a valid key looks like; a wrong key is rejected by the provider at request time.

### Key Rotation

1. Generate new keys from the provider's dashboard
2. Update environment variables or config files
3. Restart the bot
4. Revoke old keys from the provider's dashboard

## 🛡️ Pre-commit Hooks

The project includes pre-commit hooks to prevent accidental secret exposure:

### Setup
```bash
pip install pre-commit
pre-commit install
```

### Configured Hooks

1. **detect-secrets**: Scans for potential secrets in commits
    - Blocks commits containing potential API keys, passwords, etc.

2. **black**: Ensures consistent code formatting

3. **ruff**: Lints code for security issues (via `S` rules)

### Updating Baseline

If you need to add a legitimate secret-like string, update the pre-commit configuration in `.pre-commit-config.yaml` to exclude the false positive.

## ⏱️ Rate Limiting

### Per-User Rate Limiting

DiscordianAI implements per-user rate limiting to prevent abuse:

```ini
[Limits]
RATE_LIMIT=10        # Max requests per user
RATE_LIMIT_PER=60    # Time window in seconds
```

**Default:** 10 requests per 60 seconds per user.

### API Rate Limit Handling

The bot handles upstream API rate limits gracefully:

1. **Retry with Backoff**: `DEFAULT_API_RETRY_CONFIG` allows 2 attempts total
   (one initial request plus one retry). The delay is full-jitter exponential
   backoff, and 429 responses honour `Retry-After` up to 30 seconds. A
   90-second deadline stops retries even when attempts remain.
2. **Transient Failures Only**: 429, 5xx, connection errors where no request was
   established, and connect timeouts are retried. Authentication errors, read
   timeouts, exhausted quotas, and unclassified exceptions fail immediately.
3. **Circuit Breaker**: A shared per-provider breaker opens after 5 failed
   logical calls (all retries for one call count as one failure) and allows a
   single probe after 60 seconds.

```python
# Example retry configuration (matches DEFAULT_API_RETRY_CONFIG)
RetryConfig(
    max_attempts=2,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
    max_elapsed=90.0,
)
```

## 🔒 Input Validation

### Message Handling

- **Inbound text is mostly not sanitized.** For guild messages the bot removes mention tokens (`<@id>`, `<@!id>`, `<@&id>`) from the message body and trims the result before the request; DMs are left unchanged. The bot does not strip instructions, links, or markdown.
- **Outbound text is neutralised.** Messages longer than Discord's 2000-character limit are
  split, and every final chunk is sanitised for mentions and links after splitting. The
  sanitiser and splitter both call the `tree-sitter-markdown` filter
  `_filtered_code_regions()`; the public `protected_code_regions()` is its wrapper. It
  protects only a closed fence opened and closed by exactly three backticks when Discord
  would also end that fence at the same place and the text contains no other unmatched
  triple-backtick run, or a closed inline code span whose opener
  and closer are not backslash-escaped when the text uses one backtick run length and the
  span carries no emphasis, strikethrough, spoiler, or scheme-qualified link syntax. A stray
  triple-backtick run between a fence's opener and closer, or any pairing mismatch, makes
  the whole text ordinary. Tilde fences, four-or-more-backtick fences, indented blocks,
  unclosed fences, and mixed backtick runs protect nothing. Outside those regions
  parser-reported links, images, and autolinks become label text or a neutralised URL, then
  catch-all passes break every `](`, insert a zero-width space after every `://`, and
  separate `<` from a following scheme. Definition-shaped lines are kept as ordinary text
  with an invisible separator, never deleted; a trusted citation URL is left clickable.
  Only that citation's own destination is exempt, so title text and any second link after
  it are scanned as ordinary text. Mentions are neutralised everywhere, including inside
  code. A message with more than 2,048 emphasis, strikethrough, or spoiler marker characters
  skips the inline grammar and is sanitised by the catch-all passes, which keeps a
  delimiter-dense answer from stalling delivery. Nested link labels are rendered only 100
  levels deep; deeper labels become ordinary text instead of raising `RecursionError`. A
  lone UTF-16 surrogate is replaced with `?` before parsing so an unencodable character
  cannot abort the whole answer. The splitter additionally
  keeps a split-only Discord pairing for chunk boundaries when the filter protects no
  fence; those spans never suppress sanitisation. These controls apply to outbound text
  only.
- **Discord does not moderate bot messages.** Server AutoMod or channel permissions can restrict what users send, but the bot's own replies are not passed through Discord's moderation.
- **URLs are opened by provider tools.** User-supplied URLs are passed to the provider's native search and fetch tools. The bot does not fetch page content itself.

### Prompt Injection

Tool descriptions and the Perplexity instructions state that search results and fetched pages are untrusted reference material and that the model must never follow instructions found inside them. Perplexity also opens URLs through `fetch_url`; the chat path offers Ollama's `web_search` and `web_fetch` tools instead of injecting page text into a prompt.

These instructions do not compel a model to obey them. An injected page can still influence the content of an answer, so treat prompt injection as a residual risk: the directive is a mitigation, not a guarantee.

### Configuration Validation

On startup, DiscordianAI validates:

- API key presence for every configured provider and the Perplexity key format
- Provider base URLs (malformed or non-absolute URLs are fatal; well-formed
  non-standard URLs are warnings)
- Numeric ranges (rate limits and input, output, and context token caps)
- Required fields (Discord token and at least one provider credential)
- Discord presence and activity-type names

Not every invalid configuration prevents startup. Fatal errors are logged and
abort startup with a non-zero exit: missing Discord credentials, a missing key
for a configured provider, invalid Perplexity key formats, malformed or
non-absolute base URLs, non-positive rate/input/context limits,
`INPUT_TOKENS` or `PERPLEXITY_INPUT_TOKENS` below 1,000, a prompt budget that
does not fit its context window (`INPUT_TOKENS + OUTPUT_TOKENS > CONTEXT_WINDOW`,
or the Perplexity trio), output-token caps outside
1..128,000 (a fixed ceiling independent of the context window), an unknown
`ROUTER_MODE` (only `heuristic` and `clef` are accepted), and invalid presence or
activity values. A malformed integer in the file or environment is reported with
a warning and its default applies.
Warnings are logged and startup continues: well-formed non-standard provider
URLs, unusually small or large token values, high rate limits, and a missing
channel allowlist.

## 🌐 Network Security

### Connection Pooling

HTTP connections use secure defaults:

- **HTTP/2**: Enabled when the `h2` package is installed, with HTTP/1.1 fallback
- **TLS**: The default OpenAI-compatible and Perplexity endpoints use HTTPS. A custom
  `http://` base URL is accepted with a warning, so use an `https://` endpoint
  when TLS is required.
- **Timeouts**: Configured to prevent hanging connections
  - Connect: 10 seconds
  - Read: 45s (chat provider) / 60s (Perplexity)
  - Write: 10 seconds

### Native Web Tools

The bot does not validate or fetch user-supplied URLs locally. Perplexity opens
them with the Agent API's `fetch_url` tool, and Ollama-compatible chat providers
open them with `web_fetch` and `web_search` when `WEB_TOOLS` is enabled.

Tool inputs are bounded before the provider request: `query` at 500 characters,
`url` at 2,048 characters, and `max_results` at 1–10. Oversized inputs become
error tool results and are not sent. Tool output is bounded before it reaches
the model: search results at 6,000 characters and fetched page text at 8,000
characters. Content is still untrusted and is not inspected by the bot. The
residual prompt-injection risk described above applies to every page a provider
fetches.

Tools are offered only on the Ollama-compatible chat path and when `WEB_TOOLS`
is true; OpenAI endpoints receive plain chat requests.

### API Endpoints

These are the default endpoints:

| Service | Default URL Pattern |
|---------|---------------------|
| OpenAI-compatible | `https://ollama.com/v1/` by default; `https://api.openai.com/v1/`, `http(s)://localhost:11434/v1/`, and `http(s)://127.0.0.1:11434/v1/` are also accepted |
| Perplexity | `https://api.perplexity.ai/` |

A custom base URL must be an absolute `http(s)` URL; a malformed or
non-absolute value aborts startup. A well-formed URL outside these accepted
patterns is accepted with a warning, so compatible gateways can be used.

## 🐳 Docker Security

### Container Hardening

The shipped Dockerfile includes these properties:

```dockerfile
FROM python:3.12-slim-bookworm
RUN groupadd -r appgroup && useradd -r -g appgroup appuser
USER appuser
```

The container runs as the non-root `appuser` and installs no unnecessary packages.
A read-only root filesystem is optional hardening and is not enabled in the shipped
Dockerfile; adding it requires auditing every path the bot writes.

### Docker Compose Security

The shipped `docker-compose.yml` includes these properties:

```yaml
services:
  discordianai:
    # Secrets come from .env; compose adds the non-secret settings below
    env_file:
      - .env

    # Health endpoint is available on host loopback only
    ports:
      - "127.0.0.1:8080:8080"

    # Bind the health server to all container interfaces so the port works
    environment:
      - HEALTH_HOST=0.0.0.0

    # Ask the running bot for its real health
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - |
          import sys
          import urllib.error
          import urllib.request

          try:
              with urllib.request.urlopen(
                  "http://127.0.0.1:8080/health", timeout=5
              ) as response:
                  sys.exit(0 if response.status == 200 else 1)
          except (OSError, urllib.error.URLError):
              sys.exit(1)

    # Resource limits
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
```

The following compose hardening is optional and is **not enabled** in the shipped
`docker-compose.yml`:

```yaml
# Optional hardening only; not enabled in the shipped docker-compose.yml.
services:
  discordianai:
    # Explicit user override; the image already runs as non-root appuser
    user: "1000:1000"

    # Read-only root filesystem
    read_only: true

    # Limit capabilities
    cap_drop:
      - ALL
```

## 📊 Monitoring & Alerting

### Logging

- Logs are written to stderr; the supervisor or shell redirect decides where they are stored. Redirecting stdout alone produces an empty file.
- Sensitive data (API keys, tokens) is never logged
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

### Health Checks

The bot serves real health endpoints at `HEALTH_HOST:HEALTH_PORT` (default
`127.0.0.1:8080`):

- `GET /health` returns 200 only when the bot and its configured providers are healthy,
  and 503 otherwise. A provider is degraded only when its breaker is `HALF_OPEN` or a
  failure happened after its last success; an idle provider with no traffic stays healthy.
  An `OPEN` breaker is unhealthy until its recovery timeout has elapsed; after that it is
  reported healthy as recovering, because the breaker would admit a probe on the next call;
- `GET /health/live` reports process liveness and answers before the gateway connects;
- `GET /health/ready` reports readiness, including the Discord connection and provider
  health, and stays 503 until the gateway is connected.

Trailing-slash variants of all three routes return the same status and body.

The shipped `docker-compose.yml` and `Dockerfile` both define a `HEALTHCHECK` that calls
`/health` with Python's standard-library `urllib.request`; the slim image has no curl.
Compose publishes `127.0.0.1:8080:8080` on the host and sets `HEALTH_HOST=0.0.0.0` in the
container. For `docker run`, add `-p 127.0.0.1:8080:8080 -e HEALTH_HOST=0.0.0.0` to probe
the endpoint from the host.

### Recommended Monitoring

For production deployments, consider:

1. **Log aggregation**: Ship logs to centralized system
2. **API usage tracking**: Monitor token usage
3. **Error alerting**: Alert on repeated API failures
4. **Uptime monitoring**: External health checks

## 🚨 Incident Response

### If API Keys Are Exposed

1. **Immediately revoke** the exposed keys from provider dashboards:
   - OpenAI-compatible chat provider: https://ollama.com (default) or https://platform.openai.com/api-keys
   - Perplexity: https://www.perplexity.ai/settings/api
   - Discord: https://discord.com/developers/applications

2. **Generate new keys** and update your deployment

3. **Review logs** for unauthorized usage

4. **Check provider usage** for unexpected activity

### Reporting Security Issues

Please report security vulnerabilities privately via:
- GitHub Security Advisories
- Email to the maintainers

Do not open public issues for security vulnerabilities.

## ✅ Security Checklist

Before deploying to production:

- [ ] API keys stored in environment variables (not config files)
- [ ] Config files have restricted permissions (600)
- [ ] Pre-commit hooks installed and working
- [ ] Rate limiting configured appropriately
- [ ] Docker container running as non-root user
- [ ] Resource limits configured
- [ ] Logging configured (no sensitive data)
- [ ] Health monitoring in place
- [ ] Incident response plan documented
