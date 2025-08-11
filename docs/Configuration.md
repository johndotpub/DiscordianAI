# Configuration Guide

DiscordianAI uses a comprehensive configuration system supporting multiple AI services, advanced orchestration, and production-grade features.

## Configuration Sections

### Discord Configuration

Controls Discord bot behavior and connectivity.

- **`DISCORD_TOKEN`** *(required)*: Your Discord bot token from the Discord Developer Portal
- **`ALLOWED_CHANNELS`**: Comma-separated list of channel names the bot responds in (e.g., "general,bot-testing")
- **`BOT_PRESENCE`**: Bot's online status ("online", "offline", "idle", "dnd") *(default: "online")*
- **`ACTIVITY_TYPE`**: Activity type displayed ("playing", "streaming", "listening", "watching", "custom", "competing") *(default: "listening")*
- **`ACTIVITY_STATUS`**: Status message displayed with activity *(default: "Humans")*

### AI Service Configuration

Configure OpenAI and Perplexity APIs for intelligent hybrid operation.

#### OpenAI Settings
- **`OPENAI_API_KEY`**: Your OpenAI API key for GPT models *(leave empty to disable)*
- **`OPENAI_API_URL`**: OpenAI API endpoint *(default: "https://api.openai.com/v1/")*
- **`GPT_MODEL`**: Model to use: "gpt-4o-mini" (default, cost-effective), "gpt-4o", "gpt-4", "gpt-4-turbo" *(default: "gpt-4o-mini")*
  

#### Perplexity Settings  
- **`PERPLEXITY_API_KEY`**: Your Perplexity API key for web search *(leave empty to disable)*
- **`PERPLEXITY_API_URL`**: Perplexity API endpoint *(default: "https://api.perplexity.ai")*
- **`PERPLEXITY_MODEL`**: Model to use: "sonar-pro" (default, latest), "sonar" (general) *(default: "sonar-pro")*

#### Token Limits
- **`INPUT_TOKENS`**: Maximum input context tokens *(default: 120000)*
- **`OUTPUT_TOKENS`**: Maximum output tokens per response *(default: 8000)*
- **`CONTEXT_WINDOW`**: Total context window size *(default: 128000)*
- **`SYSTEM_MESSAGE`**: System prompt for AI personality *(default: "You are a helpful assistant.")*

### Rate Limiting

Prevents spam and manages API costs.

- **`RATE_LIMIT`**: Messages per time period *(default: 10)*
- **`RATE_LIMIT_PER`**: Time period in seconds *(default: 60)*

### AI Orchestrator Settings

Advanced configuration for intelligent AI service routing.

- **`LOOKBACK_MESSAGES_FOR_CONSISTENCY`**: Messages to check for follow-up consistency *(default: 6)*
- **`ENTITY_DETECTION_MIN_WORDS`**: Minimum words before entity detection *(default: 10)*  
- **`MAX_HISTORY_PER_USER`**: Maximum conversation history per user *(default: 50)*
- **`USER_LOCK_CLEANUP_INTERVAL`**: Memory cleanup interval in seconds *(default: 3600)*

### Logging

Production-ready logging configuration.

- **`LOG_FILE`**: Log file path *(default: "bot.log")*
- **`LOG_LEVEL`**: Logging verbosity ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") *(default: "INFO")*

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

# Bot presence settings  
BOT_PRESENCE=online
ACTIVITY_TYPE=watching
ACTIVITY_STATUS=you bite my shiny metal ass!

[Default]
# === OPENAI CONFIGURATION ===
# For GPT-4 series, etc. - Leave blank to disable OpenAI
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_API_URL=https://api.openai.com/v1/
GPT_MODEL=gpt-4o-mini

# === PERPLEXITY CONFIGURATION ===  
# For web search capabilities - Leave blank to disable web search
PERPLEXITY_API_KEY=your_perplexity_api_key_here
PERPLEXITY_API_URL=https://api.perplexity.ai

# === TOKEN LIMITS ===
INPUT_TOKENS=120000
OUTPUT_TOKENS=8000
CONTEXT_WINDOW=128000

# === SYSTEM MESSAGE ===
# Customize your bot's personality
SYSTEM_MESSAGE=You are Bender, a sarcastic robot from Futurama. You're crude, selfish, and love beer, but deep down you care about your friends. You automatically know when to search for current information and when to use your existing knowledge.

# No GPT-5-specific parameters are supported by the public API; do not configure

[Limits]
# Rate limiting to prevent spam
RATE_LIMIT=10
RATE_LIMIT_PER=60

[Orchestrator]
# AI Orchestrator Configuration for advanced routing and optimization
# How many recent messages to check for AI service consistency
LOOKBACK_MESSAGES_FOR_CONSISTENCY=6

# Minimum words before checking for entities in routing decisions
ENTITY_DETECTION_MIN_WORDS=10

# Maximum conversation entries per user before pruning
MAX_HISTORY_PER_USER=50

# How often to clean up inactive user locks (seconds) - default 1 hour
USER_LOCK_CLEANUP_INTERVAL=3600

[Logging]
LOG_FILE=bot.log
LOG_LEVEL=INFO
```

## Environment Variable Override

All configuration values can be overridden using environment variables. This is especially useful for Docker deployments and CI/CD pipelines:

```bash
# Discord settings
export DISCORD_TOKEN="your_token_here"
export ALLOWED_CHANNELS="general,bot-testing"

# AI service settings  
export OPENAI_API_KEY="your_openai_key"
export PERPLEXITY_API_KEY="your_perplexity_key"
export GPT_MODEL="gpt-4o-mini"

# Orchestrator settings
export LOOKBACK_MESSAGES_FOR_CONSISTENCY=8
export MAX_HISTORY_PER_USER=100

# Logging
export LOG_LEVEL="DEBUG"
```

Environment variables take precedence over `config.ini` values, allowing for flexible deployment configurations.

## CLI Arguments

- **`--conf`**: Path to the configuration file (relative to base folder if --folder is used)
- **`--folder`**: (Optional) Base folder for config and logs. If provided, config and log file paths are resolved relative to this folder unless absolute

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
- **Required Fields**: Ensures DISCORD_TOKEN and at least one API key are present
- **Value Validation**: Checks integer fields, validates rate limits, and ensures proper data types
- **Early Warnings**: Logs warnings for potentially problematic configurations

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