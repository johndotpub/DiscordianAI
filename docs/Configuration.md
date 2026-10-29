# Configuration Guide

DiscordianAI uses a comprehensive configuration system supporting multiple AI services, advanced orchestration, and production-grade features.

## Configuration Sections

### Discord Configuration

Controls Discord bot behavior and connectivity.

- **`DISCORD_TOKEN`** *(required)*: Your Discord bot token from the Discord Developer Portal
- **`ALLOWED_CHANNELS`**: Comma-separated list of channel names the bot responds in (e.g., "general,bot-testing")
- **`ALLOWED_CHANNEL_IDS`**: Comma-separated list of channel IDs the bot responds in; when set, IDs take precedence over `ALLOWED_CHANNELS` names
- **`ALLOWED_GUILDS`** / **`ALLOWED_GUILD_IDS`**: Optional guild names or IDs that narrow channel-name matching; without them, names match in every guild the bot is in
- **`BOT_PRESENCE`**: Bot's online status ("online", "offline", "idle", "dnd", "invisible") *(default: "online")*
- **`ACTIVITY_TYPE`**: Activity type displayed ("playing", "streaming", "listening", "watching", "custom", "competing") *(default: "listening")*
- **`ACTIVITY_STATUS`**: Status message displayed with activity *(default: "Humans")*

Bot-authored messages are accepted like human messages, but replies never include the bot author's mention and never authorise it in `allowed_mentions`. Two consecutive bot-authored turns are allowed per conversation; the next is dropped until a human message resets the streak. The streak is held with the conversation state and expires with `CONVERSATION_TTL_SECONDS`.

### AI Service Configuration

Configure OpenAI and Perplexity APIs for intelligent hybrid operation.

#### OpenAI Settings
- **`OPENAI_API_KEY`**: Your OpenAI API key for GPT models *(leave empty to disable)*
- **`OPENAI_API_URL`**: OpenAI API endpoint *(default: "https://api.openai.com/v1/")*
- **`GPT_MODEL`**: Model to use. GPT-6 is current: "gpt-6-luna" (default, cost-effective), "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-astra", "gpt-6-sol". Legacy GPT-5 models ("gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-pro") remain selectable until the provider retires them on 2026-12-11 *(default: "gpt-6-luna")*

The GPT-6 family is current. The provider retires the GPT-5 series on 2026-12-11; those names stay selectable until then, and `gpt-5-chat` is already retired. Validation accepts any model in the `gpt-6`, `gpt-6.1`, `gpt-5.6` and `gpt-5` families, including dated snapshots, so a new point release is usable without a code change. Names outside those families, such as `gpt-7` or `gpt6-luna`, are rejected.

#### Perplexity Settings  
- **`PERPLEXITY_API_KEY`**: Your Perplexity API key for web search *(leave empty to disable)*
- **`PERPLEXITY_API_URL`**: Perplexity API endpoint *(default: "https://api.perplexity.ai")*
- **`PERPLEXITY_MODEL`**: Model to use: "sonar-pro" (default), "sonar", "sonar-deep-research", or "sonar-reasoning-pro" *(default: "sonar-pro")*

#### Token Limits
- **`INPUT_TOKENS`**: Maximum input context tokens *(default: 120000)*
- **`OUTPUT_TOKENS`**: Maximum OpenAI output tokens per response, sent as `max_completion_tokens` *(default: 8000)*
- **`PERPLEXITY_OUTPUT_TOKENS`**: Maximum Perplexity output tokens per response, sent as `max_tokens` *(default: the value of `OUTPUT_TOKENS`)*
- **`CONTEXT_WINDOW`**: Total context window size *(default: 128000)*
- **`SYSTEM_MESSAGE`**: System prompt for AI personality *(default: "You are a helpful assistant.")*

`OUTPUT_TOKENS` and `PERPLEXITY_OUTPUT_TOKENS` mean different things. OpenAI's
`max_completion_tokens` covers reasoning tokens as well as visible output, so a small
OpenAI value can be consumed entirely by reasoning and produce an empty reply with
`finish_reason: length`. Perplexity's `max_tokens` covers output only. Both settings share
the documented maximum of 128,000; values above it stop startup, and an OpenAI value below
512 logs a warning about empty replies.

`INPUT_TOKENS` is enforced as a prompt budget. The bot estimates prompt size from the
system prompt, history, and current message using roughly four characters per token with
a 10% safety margin and a small per-message overhead. Oldest question/answer pairs are
trimmed first; an oversized message is truncated with a visible marker. The prompt budget
also leaves room for the provider's output cap inside `CONTEXT_WINDOW`; if the input and
output budgets exceed `CONTEXT_WINDOW`, the context window wins and a warning naming the
conflicting settings is logged.

#### Web Scraping Budgets
- **`MAX_URLS_PER_MESSAGE`**: Maximum URLs scraped from one message; extras are ignored *(default: 3)*
- **`MAX_TOTAL_SCRAPED_CHARS`**: Maximum combined scraped page text injected into one prompt *(default: 60000)*
- **`SCRAPE_DEADLINE_SECONDS`**: Deadline for the entire scrape phase of one message, in seconds *(default: 20)*

### Rate Limiting

Prevents spam and manages API costs.

- **`RATE_LIMIT`**: Messages per time period *(default: 10)*
- **`RATE_LIMIT_PER`**: Time period in seconds *(default: 60)*

### Connection Pooling

HTTP/2 connection pool sizes for each provider client. See [ConnectionPooling.md](ConnectionPooling.md) for tuning guidance.

- **`OPENAI_MAX_CONNECTIONS`**: Maximum concurrent OpenAI connections *(default: 50)*
- **`OPENAI_MAX_KEEPALIVE`**: OpenAI keepalive connection count *(default: 10)*
- **`PERPLEXITY_MAX_CONNECTIONS`**: Maximum concurrent Perplexity connections *(default: 30)*
- **`PERPLEXITY_MAX_KEEPALIVE`**: Perplexity keepalive connection count *(default: 5)*

### AI Orchestrator Settings

Advanced configuration for intelligent AI service routing.

- **`LOOKBACK_MESSAGES_FOR_CONSISTENCY`**: Messages to check for follow-up consistency; `0` or a negative value disables the lookup *(default: 6)*
  
- **`MAX_HISTORY_PER_USER`**: Maximum conversation history per user *(default: 50)*
- **`CONVERSATION_TTL_SECONDS`**: Idle seconds before a conversation and its lock are evicted *(default: 1800)*
- **`USER_LOCK_CLEANUP_INTERVAL`**: Memory cleanup interval in seconds *(default: 3600)*
- **`ENTITY_DETECTION_MIN_WORDS`**: Minimum message length intended for entity detection *(default: 10)*. Note: this setting is parsed into config but not yet wired into the current routing implementation; changing it has no runtime effect in this release.

### Logging

Logs are emitted to stderr as structured lines. The process supervisor or a shell redirect decides where they are stored; redirecting stdout alone produces an empty file.

- **`LOG_FILE`**: Deprecated and ignored. It is still parsed for backwards compatibility, and startup logs an INFO line naming the configured value. Redirect stderr (or both streams) or configure the supervisor's output capture instead.
- **`LOG_LEVEL`**: Logging verbosity ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") *(default: "INFO")*
- **`DISCORDIANAI_LOG_COLOR`**: Color is enabled only when the output stream is a terminal, unless the setting is present and forces it on with `1`/`true`/`yes` or off with `0`/`false`/`no`; it can be set in the `[Logging]` section or as an environment variable, and the environment wins.

### Health

Lightweight HTTP health checks for Docker and Kubernetes deployments.

- **`HEALTH_ENABLED`**: Enable or disable the health server *(default: `true`)*
- **`HEALTH_HOST`**: Bind address for the health server *(default: `127.0.0.1`)*
- **`HEALTH_PORT`**: Port for readiness/liveness probes *(default: `8080`)*
- **`HEALTH_PROVIDER_STALE_SECONDS`**: Seconds after a provider's last success before health marks it degraded *(default: `300`)*

## Operation Modes

DiscordianAI supports three distinct operation modes based on your API key configuration:

### 1. Smart Hybrid Mode (Recommended) 🧠
Configure both API keys for intelligent automatic service selection:
```ini
OPENAI_API_KEY=your_openai_api_key
PERPLEXITY_API_KEY=your_perplexity_api_key
```

### 2. OpenAI Only Mode 🤖
Only configure OpenAI for GPT-only responses:
```ini
OPENAI_API_KEY=your_openai_api_key
PERPLEXITY_API_KEY=
```

### 3. Perplexity Only Mode 🌐
Only configure Perplexity for web search responses:
```ini
OPENAI_API_KEY=
PERPLEXITY_API_KEY=your_perplexity_api_key
```

## Complete Configuration Example

Here is a complete `config.ini` file with all available options:

```ini
[Discord]
# Required: Your Discord bot token
DISCORD_TOKEN=your_discord_bot_token_here

# Channels where the bot responds (comma-separated)
ALLOWED_CHANNELS=general,bot-testing

# Optional: channel IDs take precedence over ALLOWED_CHANNELS names
ALLOWED_CHANNEL_IDS=

# Optional: narrow channel names to specific guilds (names or IDs);
# unset matches every guild the bot is in
ALLOWED_GUILDS=
ALLOWED_GUILD_IDS=

# Bot presence settings  
BOT_PRESENCE=online
ACTIVITY_TYPE=listening
ACTIVITY_STATUS=you bite my shiny metal ass!

[Default]
# === OPENAI CONFIGURATION ===
# For GPT-6 series models - Leave blank to disable OpenAI
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_API_URL=https://api.openai.com/v1/
GPT_MODEL=gpt-6-luna

# === PERPLEXITY CONFIGURATION ===  
# For web search capabilities - Leave blank to disable web search
PERPLEXITY_API_KEY=your_perplexity_api_key_here
PERPLEXITY_API_URL=https://api.perplexity.ai
PERPLEXITY_MODEL=sonar-pro

# === TOKEN LIMITS ===
INPUT_TOKENS=120000
OUTPUT_TOKENS=8000
PERPLEXITY_OUTPUT_TOKENS=8000
CONTEXT_WINDOW=128000

# === SYSTEM MESSAGE ===
# Customize your bot's personality
SYSTEM_MESSAGE=You are Bender, a sarcastic robot from Futurama. You're crude, selfish, and love beer, but deep down you care about your friends. You automatically know when to search for current information and when to use your existing knowledge.

# === WEB SCRAPING BUDGETS ===
MAX_URLS_PER_MESSAGE=3
MAX_TOTAL_SCRAPED_CHARS=60000
SCRAPE_DEADLINE_SECONDS=20

# No GPT-generation-specific parameters are supported by the public API; do not configure

[Limits]
# Rate limiting to prevent spam
RATE_LIMIT=10
RATE_LIMIT_PER=60

[ConnectionPool]
# HTTP/2 connection pool sizes for each provider
OPENAI_MAX_CONNECTIONS=50
OPENAI_MAX_KEEPALIVE=10
PERPLEXITY_MAX_CONNECTIONS=30
PERPLEXITY_MAX_KEEPALIVE=5

[Orchestrator]
# AI Orchestrator Configuration for advanced routing and optimization
# How many recent messages to check for AI service consistency (0 disables)
LOOKBACK_MESSAGES_FOR_CONSISTENCY=6

# Maximum conversation entries per user before pruning
MAX_HISTORY_PER_USER=50

# How long a conversation may sit idle before its history and lock are dropped
CONVERSATION_TTL_SECONDS=1800

# How often to clean up inactive user locks (seconds) - default 1 hour
USER_LOCK_CLEANUP_INTERVAL=3600

# Minimum words required before entity detection runs
ENTITY_DETECTION_MIN_WORDS=10

[Logging]
LOG_LEVEL=INFO
DISCORDIANAI_LOG_COLOR=false

[Health]
# HTTP health endpoint for Kubernetes / load balancer probes
HEALTH_ENABLED=true
HEALTH_HOST=127.0.0.1
HEALTH_PORT=8080
HEALTH_PROVIDER_STALE_SECONDS=300
```

## Environment Variable Override

All configuration values can be overridden using environment variables. This is especially useful for Docker deployments and CI/CD pipelines:

```bash
# Discord settings
export DISCORD_TOKEN="your_token_here"
export ALLOWED_CHANNELS="general,bot-testing"
export ALLOWED_CHANNEL_IDS="123456789012345678"
export ALLOWED_GUILDS="My Server"
export ALLOWED_GUILD_IDS="123456789012345678"
export BOT_PRESENCE="online"
export ACTIVITY_TYPE="listening"
export ACTIVITY_STATUS="Humans"

# AI service settings
export OPENAI_API_KEY="your_openai_key"
export OPENAI_API_URL="https://api.openai.com/v1/"
export PERPLEXITY_API_KEY="your_perplexity_key"
export PERPLEXITY_API_URL="https://api.perplexity.ai"
export PERPLEXITY_MODEL="sonar-pro"
export GPT_MODEL="gpt-6-luna"
export INPUT_TOKENS="120000"
export OUTPUT_TOKENS="8000"
export PERPLEXITY_OUTPUT_TOKENS="8000"
export CONTEXT_WINDOW="128000"
export SYSTEM_MESSAGE="You are a helpful assistant."

# Rate limiting and connection pooling
export RATE_LIMIT="10"
export RATE_LIMIT_PER="60"
export OPENAI_MAX_CONNECTIONS="50"
export OPENAI_MAX_KEEPALIVE="10"
export PERPLEXITY_MAX_CONNECTIONS="30"
export PERPLEXITY_MAX_KEEPALIVE="5"

# Orchestrator settings
export LOOKBACK_MESSAGES_FOR_CONSISTENCY="6"
export MAX_HISTORY_PER_USER="50"
export CONVERSATION_TTL_SECONDS="1800"
export USER_LOCK_CLEANUP_INTERVAL="3600"
export ENTITY_DETECTION_MIN_WORDS="10"

# Web scraping budgets
export MAX_URLS_PER_MESSAGE="3"
export MAX_TOTAL_SCRAPED_CHARS="60000"
export SCRAPE_DEADLINE_SECONDS="20"

# Logging and health
export LOG_FILE="bot.log"
export LOG_LEVEL="INFO"
export DISCORDIANAI_LOG_COLOR="1"
export HEALTH_ENABLED="true"
export HEALTH_HOST="127.0.0.1"
export HEALTH_PORT="8080"
```

Environment variables take precedence over `config.ini` values, allowing for flexible deployment configurations.

## CLI Arguments

- **`--conf`**: Path to the configuration file (relative to base folder if --folder is used)
- **`--folder`**: (Optional) Base folder for configuration. If provided, config paths (and the deprecated `LOG_FILE` value) are resolved relative to this folder unless absolute

### Usage Examples
```bash
# Use config.ini in current directory  
python -m src.main

# Use specific config file
python -m src.main --conf production.ini

# Use config in specific folder
python -m src.main --folder /opt/discordianai --conf bot.ini
```

## Configuration Validation & Error Handling

DiscordianAI includes comprehensive configuration validation:

### Startup Validation
- **Required Fields**: Ensures DISCORD_TOKEN and the credentials for every configured provider are present
- **Errors Abort Startup**: Missing credentials, malformed base URLs, non-positive limits, and output caps above 128,000 stop the process
- **Warnings Continue**: Unknown model names, non-standard provider base URLs, small OpenAI output caps, and other provider-tolerated settings are logged without blocking startup
- **Value Validation**: Checks integer fields, validates rate limits, and ensures proper data types

### Runtime Error Handling
- **Global Exception Handler**: Catches and logs all unhandled exceptions with full stack traces
- **Graceful Fallbacks**: Continues operation with sensible defaults when possible
- **Production Logging**: Comprehensive logging for debugging and monitoring
- **Memory Management**: Automatic cleanup and resource management

### Error Examples
```
CRITICAL: No API keys provided! Bot cannot function without either OpenAI or Perplexity API access.
WARNING: RATE_LIMIT is very high (100) - consider lowering to prevent API abuse
ERROR: Invalid log level 'VERBOSE', defaulting to INFO  
INFO: Configuration validation passed - all critical settings are valid
```

## Production Deployment Considerations

### Security
- **Never commit API keys** to version control
- **Use environment variables** in production
- **Restrict file permissions** on config files (chmod 600)
- **Monitor API usage** to prevent unexpected costs

### Performance  
- **Adjust `MAX_HISTORY_PER_USER`** based on memory constraints
- **Tune `USER_LOCK_CLEANUP_INTERVAL`** for memory management
- **Monitor `LOOKBACK_MESSAGES_FOR_CONSISTENCY`** for performance impact
- **Use appropriate `LOG_LEVEL`** for production (INFO or WARNING)

### Monitoring
- **Log rotation**: Ensure log files don't grow unbounded
- **Memory usage**: Monitor conversation history memory usage
- **API limits**: Track token usage and rate limits
- **Error rates**: Monitor error logs for issues
