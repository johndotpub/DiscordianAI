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

Configure the OpenAI-compatible chat provider (Ollama Cloud by default) and the Perplexity Agent API for intelligent hybrid operation.

#### OpenAI-Compatible Settings
- **`OPENAI_API_KEY`**: Key for the configured OpenAI-compatible provider *(leave empty to disable)*. OpenAI keys start with `sk-`; other compatible providers use their own formats, which are accepted with a warning.
- **`OPENAI_API_URL`**: Chat provider base URL. Accepted: `https://api.openai.com/v1/`, `https://ollama.com/v1/`, and `http(s)://localhost:11434/v1/` or `http(s)://127.0.0.1:11434/v1/` *(default: "https://ollama.com/v1/")*
- **`GPT_MODEL`**: Model identifier sent as configured. Any non-empty identifier is accepted; the provider decides which names are valid *(default: "deepseek-v4.1-flash:1017")*
- **`REASONING_EFFORT`**: Reasoning effort sent with chat requests only when non-empty. It is a reasoning-model parameter; valid values are model-defined, `low`, `high`, and `max` are supported by the shipped model, and `none` disables thinking. Reasoning tokens are billed as output *(default: "high")*

OpenAI remains supported by setting all three of `OPENAI_API_URL`, `GPT_MODEL`, and `OPENAI_API_KEY` to OpenAI values.

#### Perplexity Settings  
- **`PERPLEXITY_API_KEY`**: Your Perplexity API key for web search *(leave empty to disable)*
- **`PERPLEXITY_API_URL`**: Perplexity API endpoint *(default: "https://api.perplexity.ai")*
- **`PERPLEXITY_MODEL`**: Model to use. The current Agent API catalogue's Sonar model is "perplexity/sonar"; legacy Sonar names still answer on Chat Completions but are not used by this bot *(default: "perplexity/sonar")*

#### Token Limits
- **`INPUT_TOKENS`**: Maximum input context tokens *(default: 250000)*
- **`OUTPUT_TOKENS`**: Maximum chat output tokens per response, sent as `max_tokens` to Ollama-compatible providers and `max_completion_tokens` to `api.openai.com` *(default: 16384)*
- **`PERPLEXITY_OUTPUT_TOKENS`**: Maximum Perplexity output tokens per response, sent as `max_output_tokens` to the Agent API *(default: the value of `OUTPUT_TOKENS`)*
- **`CONTEXT_WINDOW`**: Total context window size *(default: 1000000)*. The default chat model's window is 1,000,000 tokens, so this value may be set that high; it feeds the prompt budget and truncation, not billing.
- **`SYSTEM_MESSAGE`**: System prompt for AI personality *(default: "You are a helpful assistant.")*

`OUTPUT_TOKENS` and `PERPLEXITY_OUTPUT_TOKENS` mean different things. The chat
provider's output cap (`max_tokens` or `max_completion_tokens`) covers reasoning tokens
as well as visible output, so a small
chat-provider value can be consumed entirely by reasoning and produce an empty reply with
`finish_reason: length`. Perplexity's `max_output_tokens` covers output only. Both settings
share the documented maximum of 1,000,000; values above it stop startup, and a chat-provider
value below 512 logs a warning about empty replies.

`INPUT_TOKENS` is enforced as a prompt budget. The bot estimates prompt size from the
system prompt, history, and current message using roughly four characters per token with
a 10% safety margin and a small per-message overhead. Oldest question/answer pairs are
trimmed first; an oversized message is truncated with a visible marker. The prompt budget
also leaves room for the provider's output cap inside `CONTEXT_WINDOW`; if the input and
output budgets exceed `CONTEXT_WINDOW`, the context window wins and a warning naming the
conflicting settings is logged.

#### Web Tools
- **`WEB_TOOLS`**: Offer native web search and page fetch to Ollama-compatible chat providers; OpenAI endpoints never receive these tools *(default: true)*

#### Vision
Image attachments are read from normal messages in allowed channels and direct messages, and sent only to the OpenAI-compatible chat provider. Perplexity never receives image data. See [Vision.md](Vision.md) for limits, fallback behavior, and the privacy note.

- **`VISION_ENABLED`**: Read image attachments on incoming messages; when false, attachments are ignored entirely *(default: true)*
- **`VISION_MAX_IMAGES`**: Maximum images accepted from one message; additional images are skipped and logged *(default: 4)*
- **`VISION_MAX_BYTES`**: Maximum size of one image in bytes, checked before and after download *(default: 5242880)*
- **`VISION_TOKEN_ESTIMATE`**: Flat prompt-token estimate charged per image during budget trimming *(default: 1000)*

### Rate Limiting

Prevents spam and manages API costs.

- **`RATE_LIMIT`**: Messages per time period *(default: 10)*
- **`RATE_LIMIT_PER`**: Time period in seconds *(default: 60)*

### Connection Pooling

HTTP/2 connection pool sizes for each provider client. See [ConnectionPooling.md](ConnectionPooling.md) for tuning guidance.

- **`OPENAI_MAX_CONNECTIONS`**: Maximum concurrent chat-provider connections *(default: 100)*
- **`OPENAI_MAX_KEEPALIVE`**: Chat-provider keepalive connection count *(default: 20)*
- **`PERPLEXITY_MAX_CONNECTIONS`**: Maximum concurrent Perplexity connections *(default: 40)*
- **`PERPLEXITY_MAX_KEEPALIVE`**: Perplexity keepalive connection count *(default: 10)*

### AI Orchestrator Settings

Advanced configuration for intelligent AI service routing.

- **`LOOKBACK_MESSAGES_FOR_CONSISTENCY`**: Messages to check for follow-up consistency; `0` or a negative value disables the lookup *(default: 6)*
  
- **`MAX_HISTORY_PER_USER`**: Maximum conversation history per user *(default: 100)*
- **`CONVERSATION_TTL_SECONDS`**: Idle seconds before a conversation and its lock are evicted *(default: 7200)*
- **`USER_LOCK_CLEANUP_INTERVAL`**: Memory cleanup interval in seconds *(default: 3600)*
- **`ENTITY_DETECTION_MIN_WORDS`**: Minimum message length intended for entity detection *(default: 10)*. Note: this setting is parsed into config but not yet wired into the current routing implementation; changing it has no runtime effect in this release.
- **`ROUTER_MODE`**: Router implementation, `heuristic` or `clef` *(default: "heuristic")*. `heuristic` is the deterministic gate and remains the fallback. `clef` sends each message to Ollama Cloud's decision model (about 0.4 seconds, billed per token); network, timeout, HTTP, or malformed-response failures fall back to the deterministic gate. `model` is not implemented and raises with a pointer to `ROUTER_MODE=clef`.
- **`ROUTER_CLEF_MODEL`**: Decision model used when `ROUTER_MODE=clef` *(default: "clef")*
- **`ROUTER_CLEF_THRESHOLD`**: Probability at or above which Clef routes to the web *(default: 0.5)*
- **`ROUTER_CLEF_TIMEOUT_MS`**: Clef request timeout in milliseconds before falling back to the deterministic gate *(default: 2000)*

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
- **`HEALTH_PROVIDER_STALE_SECONDS`**: Seconds after a provider's last success before the informational `last_success_stale` flag is set; it does not change health status *(default: `300`)*

A configured provider is `unhealthy` when its breaker is open, `degraded` when it is half-open or when a
failure happened after its last success, and `healthy` otherwise. A provider that has never been called is
healthy: silence is not a failure. The payload still reports
`last_success_age_seconds` and `last_success_stale` for diagnostics, but neither decides health.

> **No cost cap.** Routing carries no budget knob: the gate decides from the message alone, so spend
> follows the message mix rather than a configured ceiling. Measured precision also falls on trap-heavy
> input (pleasantries that contain a date or a state word); the numbers are in `docs/routing/DESIGN.md`.

## Operation Modes

DiscordianAI supports three distinct operation modes based on your API key configuration:

### 1. Smart Hybrid Mode (Recommended) 🧠
Configure both API keys for intelligent automatic service selection:
```ini
OPENAI_API_KEY=your_ollama_cloud_api_key
PERPLEXITY_API_KEY=your_perplexity_api_key
```

### 2. OpenAI-Compatible Only Mode 🤖
Only configure the chat provider for non-web responses:
```ini
OPENAI_API_KEY=your_ollama_cloud_api_key
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
# === OPENAI-COMPATIBLE CONFIGURATION ===
# Ollama Cloud is the default backend; leave the key blank to disable it.
OPENAI_API_KEY=your-ollama-cloud-api-key
OPENAI_API_URL=https://ollama.com/v1/
GPT_MODEL=deepseek-v4.1-flash:1017
REASONING_EFFORT=high

# === PERPLEXITY CONFIGURATION ===  
# For web search capabilities - Leave blank to disable web search
PERPLEXITY_API_KEY=your_perplexity_api_key_here
PERPLEXITY_API_URL=https://api.perplexity.ai
PERPLEXITY_MODEL=perplexity/sonar

# === TOKEN LIMITS ===
INPUT_TOKENS=250000
OUTPUT_TOKENS=16384
PERPLEXITY_OUTPUT_TOKENS=16384
CONTEXT_WINDOW=1000000

# === SYSTEM MESSAGE ===
# Customize your bot's personality
SYSTEM_MESSAGE=You are Bender, a sarcastic robot from Futurama. You're crude, selfish, and love beer, but deep down you care about your friends. You automatically know when to search for current information and when to use your existing knowledge.

# === WEB TOOLS ===
WEB_TOOLS=true

# === VISION ===
# Images go only to the OpenAI-compatible chat provider, never to Perplexity.
VISION_ENABLED=true
VISION_MAX_IMAGES=4
VISION_MAX_BYTES=5242880
VISION_TOKEN_ESTIMATE=1000

# No chat-provider-specific sampling parameters are supported by the public API; do not configure

[Limits]
# Rate limiting to prevent spam
RATE_LIMIT=10
RATE_LIMIT_PER=60

[ConnectionPool]
# HTTP/2 connection pool sizes for each provider
OPENAI_MAX_CONNECTIONS=100
OPENAI_MAX_KEEPALIVE=20
PERPLEXITY_MAX_CONNECTIONS=40
PERPLEXITY_MAX_KEEPALIVE=10

[Orchestrator]
# AI Orchestrator Configuration for advanced routing and optimization
# How many recent messages to check for AI service consistency (0 disables)
LOOKBACK_MESSAGES_FOR_CONSISTENCY=6

# Maximum conversation entries per user before pruning
MAX_HISTORY_PER_USER=100

# How long a conversation may sit idle before its history and lock are dropped
CONVERSATION_TTL_SECONDS=7200

# How often to clean up inactive user locks (seconds) - default 1 hour
USER_LOCK_CLEANUP_INTERVAL=3600

# Minimum words required before entity detection runs
ENTITY_DETECTION_MIN_WORDS=10

# Router implementation: heuristic (default) or clef (optional decision model)
ROUTER_MODE=heuristic
ROUTER_CLEF_MODEL=clef
ROUTER_CLEF_THRESHOLD=0.5
ROUTER_CLEF_TIMEOUT_MS=2000

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
export OPENAI_API_KEY="your_ollama_cloud_key"
export OPENAI_API_URL="https://ollama.com/v1/"
export PERPLEXITY_API_KEY="your_perplexity_key"
export PERPLEXITY_API_URL="https://api.perplexity.ai"
export PERPLEXITY_MODEL="perplexity/sonar"
export GPT_MODEL="deepseek-v4.1-flash:1017"
export REASONING_EFFORT="high"
export INPUT_TOKENS="250000"
export OUTPUT_TOKENS="16384"
export PERPLEXITY_OUTPUT_TOKENS="16384"
export CONTEXT_WINDOW="1000000"
export SYSTEM_MESSAGE="You are a helpful assistant."

# Rate limiting and connection pooling
export RATE_LIMIT="10"
export RATE_LIMIT_PER="60"
export OPENAI_MAX_CONNECTIONS="100"
export OPENAI_MAX_KEEPALIVE="20"
export PERPLEXITY_MAX_CONNECTIONS="40"
export PERPLEXITY_MAX_KEEPALIVE="10"

# Orchestrator settings
export LOOKBACK_MESSAGES_FOR_CONSISTENCY="6"
export MAX_HISTORY_PER_USER="100"
export CONVERSATION_TTL_SECONDS="7200"
export USER_LOCK_CLEANUP_INTERVAL="3600"
export ENTITY_DETECTION_MIN_WORDS="10"
export ROUTER_MODE="heuristic"
export ROUTER_CLEF_MODEL="clef"
export ROUTER_CLEF_THRESHOLD="0.5"
export ROUTER_CLEF_TIMEOUT_MS="2000"

# Native web tools
export WEB_TOOLS="1"

# Image attachments (OpenAI-compatible chat provider only)
export VISION_ENABLED="true"
export VISION_MAX_IMAGES="4"
export VISION_MAX_BYTES="5242880"
export VISION_TOKEN_ESTIMATE="1000"

# Logging and health
export LOG_FILE="bot.log"
export LOG_LEVEL="INFO"
export DISCORDIANAI_LOG_COLOR="1"
export HEALTH_ENABLED="true"
export HEALTH_HOST="127.0.0.1"
export HEALTH_PORT="8080"
export HEALTH_PROVIDER_STALE_SECONDS="300"
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
- **Errors Abort Startup**: Missing credentials, malformed base URLs, non-positive limits, and output caps above 1,000,000 stop the process
- **Warnings Continue**: Non-standard provider base URLs, small chat-provider output caps, non-`sk-` OpenAI-compatible keys, and other provider-tolerated settings are logged without blocking startup
- **Value Validation**: Checks integer fields, validates rate limits, and ensures proper data types

### Runtime Error Handling
- **Global Exception Handler**: Catches and logs all unhandled exceptions with full stack traces
- **Graceful Fallbacks**: Continues operation with sensible defaults when possible
- **Production Logging**: Comprehensive logging for debugging and monitoring
- **Memory Management**: Automatic cleanup and resource management

### Error Examples
```
CRITICAL: No API keys provided! Bot cannot function without either an OpenAI-compatible provider or Perplexity API access.
WARNING: RATE_LIMIT very high (101). Consider lower value to prevent abuse.
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
