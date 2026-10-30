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

3. **Docker Secrets** (optional hardening; not enabled in the shipped compose file)
   ```yaml
   # Optional hardening only; not enabled in the shipped docker-compose.yml.
   services:
     discordianai:
       secrets:
         - discord_token
         - openai_key
   secrets:
     discord_token:
       file: ./secrets/discord_token.txt
     openai_key:
       file: ./secrets/openai_key.txt
   ```

### Key Format Validation

DiscordianAI validates API key formats before use:

| Service | Expected Format | Example |
|---------|-----------------|---------|
| OpenAI | `sk-` + at least 20 letters, digits, `-` or `_` | `sk-abc123...` |
| Perplexity | `pplx-` + at least 20 letters, digits, `-` or `_` | `pplx-xyz789...` |

Invalid formats will produce clear error messages with links to the respective API key management pages.

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
2. **Transient Failures Only**: 429, 5xx, connection errors, and connect
   timeouts are retried. Authentication errors, read timeouts, and exhausted
   quotas fail immediately.
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

- **Inbound text is not sanitized.** The message body is sent to the configured provider unchanged; the bot does not strip instructions, links, or markdown before the request.
- **Outbound text is neutralised.** Messages longer than Discord's 2000-character limit are split, and model output is sanitised for mentions and links before delivery. These controls apply to outbound text only.
- **Discord does not moderate bot messages.** Server AutoMod or channel permissions can restrict what users send, but the bot's own replies are not passed through Discord's moderation.
- **URLs are validated before scraping.** Every user-supplied URL is checked by the SSRF protections below before any request is made.

### Prompt Injection

Scraped page text is wrapped in `<untrusted_webpage_content>` tags. A data-only directive tells the model to treat the block as data and ignore instructions inside it, and delimiter lookalikes are escaped case-insensitively, including whitespace and self-closing variants. This reduces the chance that a page can close the block or pass itself off as the system prompt.

The delimiters do not compel a model to obey the directive. Only scraped page text receives this treatment; user messages and conversation history are not wrapped. An injected page can still influence the content of an answer, so treat prompt injection as a residual risk: the wrapper is a mitigation, not a guarantee.

### Configuration Validation

On startup, DiscordianAI validates:

- API key presence and format for every configured provider
- Provider base URLs (malformed or non-absolute URLs are fatal; well-formed
  non-standard URLs are warnings)
- Numeric ranges (rate limits and input, output, and context token caps)
- Required fields (Discord token and at least one provider credential)
- Discord presence and activity-type names

Not every invalid configuration prevents startup. Fatal errors are logged and
abort startup with a non-zero exit: missing Discord or provider credentials,
invalid API-key formats, malformed or non-absolute base URLs, non-integer or
non-positive rate/input/context limits, output-token caps outside 1..128,000,
and invalid presence or activity values. Warnings are logged and startup
continues: unknown model names, well-formed non-standard provider URLs,
unusually small or large token values, high rate limits, and a missing channel
allowlist.

## 🌐 Network Security

### Connection Pooling

HTTP connections use secure defaults:

- **HTTP/2**: Enabled when the `h2` package is installed, with HTTP/1.1 fallback
- **TLS**: The default OpenAI and Perplexity endpoints use HTTPS. A custom
  `http://` base URL is accepted with a warning, so use an `https://` endpoint
  when TLS is required.
- **Timeouts**: Configured to prevent hanging connections
  - Connect: 10 seconds
  - Read: 45s (OpenAI) / 60s (Perplexity)
  - Write: 10 seconds

### Web Scraper SSRF Protection

The web scraper validates the URL inside the fetch path itself, so a caller
cannot bypass the check by forgetting to call `is_scrapable_url`. Automatic
redirects are disabled on the scrape client: redirects are followed manually
for at most three hops, and the initial URL and every `Location` are resolved
and checked before use. A redirect to a non-global address is refused without
reading its body.

A URL is accepted only when every address returned for its hostname passes
Python's `ipaddress.is_global()` check and is not multicast. IPv4-mapped IPv6
and NAT64 addresses are unwrapped before that check, so a blocked IPv4 target
cannot slip through inside an IPv6 form. The main rejected classes are:

| Class | Range or address |
| --- | --- |
| IPv4 loopback | `127.0.0.0/8` |
| IPv4 private | `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` |
| IPv4 link-local | `169.254.0.0/16` |
| IPv4 CGNAT | `100.64.0.0/10` |
| IPv4 unspecified | `0.0.0.0` |
| IPv6 loopback | `::1` |
| IPv6 link-local | `fe80::/10` |
| IPv6 unique-local | `fc00::/7` |
| Other non-global | multicast, documentation ranges, and anything else `ipaddress` reports as non-global |
| NAT64-encoded blocked IPv4 | `64:ff9b::/96` wrapping a non-global IPv4 address |

If a hostname resolves to a mix of global and non-global addresses, the URL
is refused.

For plain HTTP the connection is pinned to a vetted address: the request URL
uses that IP and the original hostname is sent in the `Host` header, so a
second DNS answer cannot redirect the connection. HTTPS is deliberately not
pinned because connecting to a bare IP address would break SNI and certificate
validation. Instead the hostname is resolved and checked immediately before
the request, but httpx performs its own lookup when it connects. A
DNS-rebinding attacker therefore has a small window between the validation
lookup and the connection lookup. This residual risk is accepted deliberately
in exchange for correct TLS verification.

### API Endpoints

These are the default endpoints:

| Service | Default URL Pattern |
|---------|---------------------|
| OpenAI | `https://api.openai.com/v1/` |
| Perplexity | `https://api.perplexity.ai/` |

A custom base URL must be an absolute `http(s)` URL; a malformed or
non-absolute value aborts startup. A well-formed URL outside these default
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
  and 503 otherwise;
- `GET /health/live` reports process liveness;
- `GET /health/ready` reports readiness, including the Discord connection and provider
  health.

The shipped `docker-compose.yml` and `Dockerfile` both define a `HEALTHCHECK` that calls
`/health` with Python's standard-library `urllib.request`; the slim image has no curl.
Compose publishes `127.0.0.1:8080:8080` on the host and sets `HEALTH_HOST=0.0.0.0` in the
container. For `docker run`, add `-p 127.0.0.1:8080:8080 -e HEALTH_HOST=0.0.0.0` to probe
the endpoint from the host.

### Recommended Monitoring

For production deployments, consider:

1. **Log aggregation**: Ship logs to centralized system
2. **API usage tracking**: Monitor token usage and costs
3. **Error alerting**: Alert on repeated API failures
4. **Uptime monitoring**: External health checks

## 🚨 Incident Response

### If API Keys Are Exposed

1. **Immediately revoke** the exposed keys from provider dashboards:
   - OpenAI: https://platform.openai.com/api-keys
   - Perplexity: https://www.perplexity.ai/settings/api
   - Discord: https://discord.com/developers/applications

2. **Generate new keys** and update your deployment

3. **Review logs** for unauthorized usage

4. **Check billing** for unexpected charges

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
