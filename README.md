[![CI](https://github.com/johndotpub/DiscordianAI/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/ci.yml)
[![CodeQL](https://github.com/johndotpub/DiscordianAI/actions/workflows/github-code-scanning/codeql/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/github-code-scanning/codeql)
[![codecov](https://codecov.io/gh/johndotpub/DiscordianAI/branch/main/graph/badge.svg)](https://codecov.io/gh/johndotpub/DiscordianAI)
[![Security: pip-audit](https://img.shields.io/badge/security-pip--audit-blueviolet)](https://pypi.org/project/pip-audit/)

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://pre-commit.com/)

[![Discord.py](https://img.shields.io/badge/discord.py-2.6.4-5865F2.svg?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--5-412991.svg?logo=openai&logoColor=white)](https://openai.com/)
[![Perplexity](https://img.shields.io/badge/Perplexity-Sonar--Pro-20B2AA.svg)](https://www.perplexity.ai/)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](http://unlicense.org/)

[![GitHub release](https://img.shields.io/github/v/release/johndotpub/DiscordianAI)](https://github.com/johndotpub/DiscordianAI/releases)
[![GitHub last commit](https://img.shields.io/github/last-commit/johndotpub/DiscordianAI)](https://github.com/johndotpub/DiscordianAI/commits/main)
[![GitHub issues](https://img.shields.io/github/issues/johndotpub/DiscordianAI)](https://github.com/johndotpub/DiscordianAI/issues)

# DiscordianAI

DiscordianAI is an **advanced Discord bot** with sophisticated AI orchestration, conversation consistency, and production-grade thread-safe architecture. It intelligently uses multiple AI services to provide the best responses with **three operation modes**:

1. **🧠 Smart Hybrid Mode** - Automatically chooses between OpenAI's GPT models and Perplexity's web search with conversation consistency
2. **🤖 OpenAI Only** - Uses OpenAI for all responses  
3. **🔍 Perplexity Only** - Uses web search for all responses with proper citations

## ✨ Advanced Features

### 🔄 **AI Service Consistency System**
- **Follow-up Detection**: Automatically detects when users ask follow-up questions
- **Context Preservation**: Routes follow-ups to the same AI service for conversational continuity  
- **Metadata Tracking**: Stores AI service information with each response for intelligent routing

### 🎯 **Smart AI Orchestration**
- **Semantic Analysis**: Advanced pattern matching to determine optimal AI service
- **Entity Detection**: Recognizes proper nouns, companies, and specific topics for routing
- **Time Sensitivity**: Automatically detects time-sensitive queries for web search
- **Configurable Intelligence**: Fine-tune routing behavior with advanced configuration options

### 🔗 **Enhanced Discord Integration** 
- **🌐 Clickable Citations**: Perplexity responses with citations display as beautiful Discord embeds with clickable `[[1]](url)` hyperlinks
- **📱 Smart Embed Usage**: Automatically creates embeds for citation-rich responses, plain text for conversations
- **🔧 Modern API Support**: Supports latest Perplexity API format with `citations` and `search_results` metadata fields
- **✂️ Smart Message Splitting**: Intelligently splits long responses while preserving embed functionality and content integrity
- **🔒 Thread-Safe Operations**: Handles concurrent users safely without data corruption

### 🛡️ **Production-Grade Architecture**
- **Thread Safety**: Per-user locking prevents race conditions in concurrent scenarios
- **Memory Management**: Automatic cleanup of inactive user data to prevent memory leaks
- **Error Recovery**: Comprehensive error handling with graceful fallbacks
- **Performance Optimization**: Pre-compiled regex patterns, optimized data structures, and HTTP/2 connection pooling
- **Centralized Configuration**: Single source of truth for all patterns and settings

### ⚡ **High-Performance Connection Pooling**
- **HTTP/2 Support**: Multiplexed connections for better throughput
- **API-Specific Tuning**: Optimized connection pools for OpenAI (50 max) and Perplexity (30 max)
- **Shared Connections**: Multiple users share connection pools efficiently
- **Rate Limit Compliance**: Respects OpenAI (500 RPM) and Perplexity API limits
- **Memory Efficient**: Supports 10k+ users with <100MB conversation memory

## Requirements

- **Python**: 3.10+ (3.10, 3.11, 3.12 supported)
- **Discord Bot Token**: From [Discord Developer Portal](https://discord.com/developers/applications)
- **OpenAI API Key**: From [OpenAI Platform](https://platform.openai.com/api-keys) (optional)
- **Perplexity API Key**: From [Perplexity AI](https://www.perplexity.ai/settings/api) (optional)

## API Keys (Choose Your Mode)

- **OpenAI API Key**: Get from [OpenAI Platform](https://platform.openai.com/api-keys)
- **Perplexity API Key** (for web search): Get from [Perplexity](https://www.perplexity.ai/settings/api)

*You can use one or both keys depending on your preferred operation mode*

### Features

- Strict error checking: The control script exits on any error and recognizes failures in pipelines.
- Customizable configurations: The control script allows for different modes of operation and configurations.
- Error Handling: The control script logs errors and exits on failure.
- Process Handling: The control script terminates existing instances of the bot before starting a new one.
- Logging: The app logs events with timestamps for better tracking.
- Rate Limiting: Implements rate limiting to prevent users from spamming commands.
- Conversation History: Maintains conversation history for each user to provide context-aware responses.
- Activity Status: Configurable activity status to display what the bot is doing.
- Direct Message Handling: Processes direct messages separately from channel messages.
- Channel Message Handling: Processes messages in specific channels where the bot is mentioned.
- Smart Message Splitting: Intelligently splits long messages while preserving content integrity and respecting Discord's limits.
- Global Exception Handling: Catches and logs unhandled exceptions to prevent crashes.
- Shard Support: Supports sharding for better scalability and performance.

# Installation

1. Clone the repository to your local machine.
2. Install the required packages using pip: `pip install -r requirements.txt`
3. Rename `config.ini.example` to `config.ini` and fill in the required configuration details.

# Configuration

The `config.ini` file supports all three operation modes with comprehensive configuration options:

## Operation Modes

### 🧠 Smart Hybrid Mode (Recommended)
The bot automatically analyzes each message and chooses the best AI service:
- **Time-sensitive questions** → Perplexity (web search)
- **Creative/coding requests** → OpenAI  
- **Factual queries** → Perplexity
- **Conversations** → OpenAI

```ini
OPENAI_API_KEY=your_openai_key_here
PERPLEXITY_API_KEY=your_perplexity_key_here
```

### 🤖 OpenAI Only Mode
Uses OpenAI for all responses:
```ini
OPENAI_API_KEY=your_openai_key_here
PERPLEXITY_API_KEY=
```

### 🔍 Perplexity Only Mode  
Uses web search for all responses with citations:
```ini
OPENAI_API_KEY=
PERPLEXITY_API_KEY=your_perplexity_key_here
```

## Configuration Sections

### Discord Settings
- `DISCORD_TOKEN`: Your Discord bot token
- `ALLOWED_CHANNELS`: Comma-separated channel names where bot responds
- `BOT_PRESENCE`: Bot status (online, idle, dnd, invisible)
- `ACTIVITY_TYPE`: Activity type (playing, streaming, listening, watching, competing)
- `ACTIVITY_STATUS`: Custom activity message

### AI Configuration
- `OPENAI_API_KEY`: OpenAI API key for GPT models (leave blank to disable)
- `OPENAI_API_URL`: OpenAI API endpoint (default: https://api.openai.com/v1/)
- `GPT_MODEL`: OpenAI model (gpt-5-mini, gpt-5, gpt-5-nano, gpt-5-chat)
- `PERPLEXITY_API_KEY`: Perplexity API key for web search (leave blank to disable)
- `PERPLEXITY_API_URL`: Perplexity API endpoint (default: https://api.perplexity.ai)
- `PERPLEXITY_MODEL`: Perplexity model (sonar-pro, sonar)

### Token & Rate Limits
- `INPUT_TOKENS`: Maximum input context size (default: 120000)
- `OUTPUT_TOKENS`: Maximum response tokens (default: 8000)
- `CONTEXT_WINDOW`: Context window size (default: 128000)
- `RATE_LIMIT`: Messages per time period (default: 10)  
- `RATE_LIMIT_PER`: Time period in seconds (default: 60)

### Connection Pooling (Performance)
- `OPENAI_MAX_CONNECTIONS`: Max concurrent connections to OpenAI API (default: 50)
- `OPENAI_MAX_KEEPALIVE`: Max keepalive connections for OpenAI (default: 10)
- `PERPLEXITY_MAX_CONNECTIONS`: Max concurrent connections to Perplexity API (default: 30)
- `PERPLEXITY_MAX_KEEPALIVE`: Max keepalive connections for Perplexity (default: 5)

### System & Logging
- `SYSTEM_MESSAGE`: AI personality/instructions
- `LOG_FILE`: Log file path (default: bot.log)
- `LOG_LEVEL`: Logging verbosity (INFO, DEBUG, etc.)

## Smart Detection Examples

The bot automatically knows what to do - no manual commands needed!

**Automatically uses web search for:**
- "What's happening in AI today?" ← Time-sensitive
- "How's Tesla stock doing?" ← Financial data
- "Tell me about the recent SpaceX launch" ← Current events
- "What's the weather like in Tokyo?" ← Current information

**Automatically uses OpenAI for:**
- "Write me a poem about robots" ← Creative
- "How do I fix this Python error?" ← Technical  
- "What do you think about philosophy?" ← Conversational
- "Hello! How are you?" ← Greeting

Here is the unified `config.ini` example:

```ini
[Discord]
DISCORD_TOKEN=your_discord_bot_token_here
ALLOWED_CHANNELS=general,bot-testing
BOT_PRESENCE=online
ACTIVITY_TYPE=watching
ACTIVITY_STATUS=you bite my shiny metal ass!

[Default]
# Both APIs for smart hybrid mode
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_API_URL=https://api.openai.com/v1/
GPT_MODEL=gpt-5-mini
PERPLEXITY_API_KEY=your_perplexity_api_key_here
PERPLEXITY_MODEL=sonar-pro

INPUT_TOKENS=120000
OUTPUT_TOKENS=8000
CONTEXT_WINDOW=128000
SYSTEM_MESSAGE=You are Bender from Futurama. You automatically know when to search for current information.

#

[Limits]
RATE_LIMIT=10
RATE_LIMIT_PER=60

[Logging]
LOG_FILE=bot.log
LOG_LEVEL=INFO
```

# Discord Bot Setup

To use this bot, you will need to create a Discord bot and invite it to your server. Here are the steps to do so:

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create a new application.
2. Click on the "Bot" tab and then click "Add Bot".
3. Copy the bot token and paste it into the `DISCORD_TOKEN` field in the `config.ini` file.
4. Under the "OAuth2" tab, select the "bot" scope and then select the permissions you want the bot to have.
5. Copy the generated OAuth2 URL and paste it into your web browser. This will allow you to invite the bot to your server.

# Usage

To start the bot, run the following command:

```bash
python -m src.main --conf config.ini --folder /path/to/base/folder
```

- `--conf`: Path to the configuration file (relative to base folder if --folder is used).
- `--folder`: (Optional) Base folder for config and logs. If provided, config and log file paths are resolved relative to this folder unless absolute.

The bot will log in to Discord and start listening for messages in the configured channels. When a message is received, the bot will send the message to the OpenAI API and wait for a response. The response will be sent back to the user who sent the message.

## Error Handling

A global exception handler is set up to log any unhandled exceptions, ensuring robust error reporting and easier debugging.

## Daemon Mode

Daemon/background mode is handled by the `discordian.sh` shell script, which supports `-d/--daemon`, `-c/--config`, and `-f/--folder` arguments. See the Daemon section below for details.

## Detailed Documentation

For more in-depth information about the DiscordianAI project, please refer to the following documentation files in the `docs/` directory:

### 🏗️ Architecture & Design
- **[Architecture](./docs/Architecture.md)** : System design, components, request flow diagrams, and design patterns
- **[Smart AI Mode](./docs/HybridMode.md)** : Complete guide to intelligent multi-AI operation with smart detection

### ⚙️ Configuration & Setup
- [Configuration](./docs/Configuration.md) : Detailed instructions on configuring the Discord bot and AI API settings
- [Setup](./docs/Setup.md) : Step-by-step guide on how to set up and run the Discord bot
- [Python Versions](./docs/Python_Versions.md) : Supported Python versions and compatibility notes

### 🤖 AI Integration
- [OpenAI](./docs/OpenAI.md) : How the bot uses OpenAI GPT API to generate responses
- [Perplexity](./docs/Perplexity.md) : Web search integration with Perplexity AI and citations
- [Web Scraping](./docs/WebScraping.md) : URL content extraction for context-aware responses

### 💬 Message Handling
- **[Message Splitting](./docs/MessageSplitting.md)** : Advanced message splitting with recursion limit protection
- [Embed Limits](./docs/EmbedLimits.md) : Discord embed size limits and handling strategies

### 🔧 Infrastructure
- [Connection Pooling](./docs/ConnectionPooling.md) : HTTP/2 connection pooling for API performance
- [Docker](./docs/Docker.md) : Instructions on containerizing the Discord bot
- [Daemon](./docs/Daemon.md) : Running the Discord bot as a background service

### 🛡️ Security & Development
- **[Security](./docs/Security.md)** : API key management, rate limiting, and security best practices
- [Development](./docs/Development.md) : Modern development workflow and linting tools

## Development & Testing

### Install Dev Dependencies

```bash
pip install -e .[dev]
```

### Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=term-missing

# Run specific test file
pytest tests/test_smart_orchestrator.py
```

### Linting & Formatting

**Modern Approach (Recommended):**
```bash
# Format code
black .

# Lint and auto-fix
ruff check --fix .

# Run tests
pytest -q
```

**Full Quality Check:**
```bash
# Check formatting
black --check .

# Check linting
ruff check .

# Run tests
pytest -q
```

### Using Tox (CI/CD)

```bash
# Run all environments
tox

# Run specific environment
tox -e py310
tox -e lint
tox -e test

# Run in parallel for faster execution
tox --parallel auto
```

### Continuous Integration

All pushes and pull requests are automatically checked with:
- **Black** for code formatting
- **Ruff** for comprehensive linting and import sorting
- **Pytest** for testing with coverage reporting
- **GitHub Actions** for automated CI/CD

# Daemon Control Script

`discordian.sh` is a bash script for launching a DiscordianAI bot with customizable configurations. It is suitable for both manual execution and running via crontab.

### Usage

The script accepts the following command line arguments:

- `-d` or `--daemon`: Runs the bot in daemon mode with no output to the terminal.
- `-c` or `--config`: Allows the use of a custom configuration file. The next argument should be the path to the configuration file.
- `-f` or `--folder`: Allows the use of a base folder. The next argument should be the path to the base folder.

### Daemon Example

```bash
./discordian.sh -d -c /path/to/config.ini -f /path/to/base/folder
```

This command will run the bot in daemon mode, using the configuration file at `/path/to/config.ini` and the base folder at `/path/to/base/folder`.

# Security Best Practices

## API Key Management

- **Never commit API keys** to version control
- **Use environment variables** in production:
  ```bash
  export DISCORD_TOKEN="your_token"
  export OPENAI_API_KEY="your_openai_key"
  export PERPLEXITY_API_KEY="your_perplexity_key"
  ```
- **Restrict config file permissions**: `chmod 600 config.ini`
- **Rotate API keys regularly** and monitor usage
- **Use separate keys for development and production**

## Configuration Security

- Keep `config.ini` in `.gitignore` (already configured)
- Use strong, unique Discord bot tokens
- Regularly review and update dependencies for security patches
- Enable pre-commit hooks to prevent accidental secret commits:
  ```bash
  pip install pre-commit
  pre-commit install
  ```

## Production Deployment

- Run the bot with minimal required permissions
- Use Docker for isolation and easier updates
- Monitor logs for suspicious activity
- Set up alerts for authentication failures
- Regularly backup configuration (without secrets)

## Rate Limiting & Backoff

The bot implements comprehensive rate limiting and error recovery:

- **Per-user rate limiting**: Prevents abuse (default: 10 messages per 60 seconds)
- **Exponential backoff**: Automatic retry with increasing delays (1s, 2s, 4s...)
- **Circuit breaker pattern**: Prevents cascade failures when APIs are down
- **Jitter**: Random delay variation prevents thundering herd problems
- **Non-retryable errors**: Auth errors fail fast without retries

### Rate Limit Configuration

```ini
[Limits]
RATE_LIMIT=10        # Messages per time period
RATE_LIMIT_PER=60    # Time period in seconds
```

### Error Recovery Behavior

- **Rate limit errors (429)**: Retry after 30 seconds
- **Timeout errors**: Retry after 10 seconds with exponential backoff
- **Server errors (5xx)**: Retry after 60 seconds
- **Network errors**: Retry after 15 seconds
- **Auth errors (401)**: Fail immediately (no retry)

The bot automatically handles these scenarios and provides user-friendly error messages without exposing internal details.

# Contributing

Contributions are welcome! Please open an issue or pull request on the GitHub repository.

# Contact

If you have any questions or concerns, please contact github@john.pub

# License

This project is licensed under the Unlicense - see the [LICENSE](LICENSE) file for details.
