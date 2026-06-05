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

3. **Docker Secrets** (Production containers)
   ```yaml
   # docker-compose.yml
   services:
     bot:
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
| OpenAI | `sk-` + 32+ alphanumeric chars | `sk-abc123...` |
| Perplexity | `pplx-` + 32+ alphanumeric chars | `pplx-xyz789...` |

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

1. **Flat Jittered Retry**: Automatic retry with a randomized 2.0-4.0 second delay
2. **Limited Attempts**: Up to 2 attempts total
3. **Circuit Breaker**: Stops requests after repeated failures

```python
# Example retry configuration (matches DEFAULT_API_RETRY_CONFIG)
RetryConfig(
    max_attempts=2,
    base_delay=4.0,
    max_delay=4.0,
    exponential_base=1.0,
    jitter=True
)
```

## 🔒 Input Validation

### Message Sanitization

All user input is processed through sanitization:

- **Length limits**: Messages exceeding Discord's 2000 character limit are split
- **Content filtering**: Handled by Discord's built-in moderation
- **URL validation**: URLs are validated before scraping

### Configuration Validation

On startup, DiscordianAI validates:

- API key formats
- URL patterns (must match expected API endpoints)
- Numeric ranges (rate limits, token counts)
- Required fields (Discord token)

Invalid configurations produce clear error messages and prevent startup.

## 🌐 Network Security

### Connection Pooling

HTTP connections use secure defaults:

- **HTTP/2**: Enabled for better performance and security
- **TLS**: All API connections use HTTPS
- **Timeouts**: Configured to prevent hanging connections
  - Connect: 10 seconds
  - Read: 45s (OpenAI) / 60s (Perplexity)
  - Write: 10 seconds

### Web Scraper SSRF Protection

The web scraper validates URLs before fetching them and rejects non-public
targets. Hostnames are resolved first, and private, loopback, link-local, and
other non-global IP ranges are blocked before any request is made.

### API Endpoints

Only these endpoints are allowed:

| Service | Allowed URL Pattern |
|---------|---------------------|
| OpenAI | `https://api.openai.com/v1/` |
| Perplexity | `https://api.perplexity.ai/` |

Custom API URLs are validated against these patterns.

## 🐳 Docker Security

### Container Hardening

The Dockerfile follows security best practices:

```dockerfile
# Non-root user (recommended addition)
RUN useradd -m -u 1000 appuser
USER appuser

# Read-only filesystem where possible
# No unnecessary packages
FROM python:3.12-slim-bookworm
```

### Docker Compose Security

```yaml
services:
  discordianai:
    # Don't run as root
    user: "1000:1000"
    
    # Read-only root filesystem
    read_only: true
    
    # Limit capabilities
    cap_drop:
      - ALL
    
    # Resource limits
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '1.0'
```

## 📊 Monitoring & Alerting

### Logging

- Logs are written to configurable file location
- Sensitive data (API keys, tokens) is never logged
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

### Health Checks

The bot includes health check capabilities:

- API connectivity monitoring
- Model availability validation
- Connection pool health metrics

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
