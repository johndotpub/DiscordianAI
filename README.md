[![Flake8 and Pytest](https://github.com/johndotpub/DiscordianAI/actions/workflows/flake8-pytest.yml/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/flake8-pytest.yml) [![CodeQL](https://github.com/johndotpub/DiscordianAI/actions/workflows/github-code-scanning/codeql/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/github-code-scanning/codeql) [![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](http://unlicense.org/)

# Description

DiscordianAI is an **advanced Discord bot** with sophisticated AI orchestration, conversation consistency, and production-grade thread-safe architecture. It intelligently uses multiple AI services to provide the best responses with **three operation modes**:

1. **🧠 Smart Hybrid Mode** - Automatically chooses between OpenAI's GPT-5 and Perplexity's web search with conversation consistency
2. **🤖 OpenAI Only** - Uses GPT-5 for all responses  
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
- **Clickable Citations**: Converts numbered citations [1], [2] to clickable Discord hyperlinks
- **Smart Embed Suppression**: Prevents link preview clutter with multiple citations
- **Message Splitting**: Intelligently splits long responses while preserving formatting
- **Thread-Safe Operations**: Handles concurrent users safely without data corruption

### 🛡️ **Production-Grade Architecture**
- **Thread Safety**: Per-user locking prevents race conditions in concurrent scenarios
- **Memory Management**: Automatic cleanup of inactive user data to prevent memory leaks
- **Error Recovery**: Comprehensive error handling with graceful fallbacks
- **Performance Optimization**: Pre-compiled regex patterns and optimized data structures

# Requirements

- Bash
- Python 3.10 or Higher
- Python Modules
  - discord.py
  - openai
  - websockets

## API Keys (Choose Your Mode)

- **OpenAI API Key** (for GPT-5): Get from [OpenAI Platform](https://platform.openai.com/api-keys)
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
- Automatic Message Splitting: Automatically splits long messages to fit within Discord's message length limits.
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
- **Creative/coding requests** → GPT-5  
- **Factual queries** → Perplexity
- **Conversations** → GPT-5

```ini
OPENAI_API_KEY=your_openai_key_here
PERPLEXITY_API_KEY=your_perplexity_key_here
```

### 🤖 OpenAI Only Mode
Uses GPT-5 for all responses:
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
- `GPT_MODEL`: OpenAI model (gpt-4o-mini, gpt-4o, gpt-4, gpt-4-turbo, gpt-5)
- `PERPLEXITY_API_KEY`: Perplexity API key for web search (leave blank to disable)
- `PERPLEXITY_API_URL`: Perplexity API endpoint (default: https://api.perplexity.ai)
- `PERPLEXITY_MODEL`: Perplexity model (sonar-pro, sonar)

### GPT-5 Advanced Parameters
- `REASONING_EFFORT`: Thinking depth (minimal, low, medium, high)
- `VERBOSITY`: Response length (low, medium, high)

### Token & Rate Limits
- `INPUT_TOKENS`: Maximum input context size (default: 120000)
- `OUTPUT_TOKENS`: Maximum response tokens (default: 8000)
- `CONTEXT_WINDOW`: Context window size (default: 128000)
- `RATE_LIMIT`: Messages per time period (default: 10)  
- `RATE_LIMIT_PER`: Time period in seconds (default: 60)

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

**Automatically uses GPT-5 for:**
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
GPT_MODEL=gpt-4o-mini
PERPLEXITY_API_KEY=your_perplexity_api_key_here
PERPLEXITY_MODEL=sonar-pro

INPUT_TOKENS=120000
OUTPUT_TOKENS=8000
CONTEXT_WINDOW=128000
SYSTEM_MESSAGE=You are Bender from Futurama. You automatically know when to search for current information.

# GPT-5 advanced parameters
REASONING_EFFORT=medium
VERBOSITY=medium

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

- **[Smart AI Mode](./docs/HybridMode.md)** : Complete guide to intelligent multi-AI operation with smart detection
- [Configuration](./docs/Configuration.md) : Detailed instructions on how to configure the Discord bot and AI API settings  
- [Daemon](./docs/Daemon.md) : Information on how to run the Discord bot as a daemon
- [Docker](./docs/Docker.md) : Instructions on how to containerize the Discord bot using Docker
- [OpenAI](./docs/OpenAI.md) : Information on how the Discord bot uses the OpenAI GPT API to generate responses
- [Setup](./docs/Setup.md) : Step-by-step guide on how to set up and run the Discord bot

## Development & Testing

### Install Dev Dependencies

```bash
pip install -e .[dev]
```

### Run Tests

```bash
pytest
```

### Linting & Formatting

- **flake8:**
  ```bash
  flake8 .
  ```
- **black (check only):**
  ```bash
  black --check .
  ```
- **isort (check only):**
  ```bash
  isort --check .
  ```
- **autopep8 (auto-fix):**
  ```bash
  autopep8 -r . --in-place
  ```

### Full Workflow

To run all checks and tests:

```bash
flake8 .
black --check .
isort --check .
pytest
```

To auto-fix formatting:

```bash
black .
isort .
autopep8 -r . --in-place
```

### Continuous Integration

All pushes and pull requests are automatically checked with flake8 and pytest via GitHub Actions.

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

# Contributing

Contributions are welcome! Please open an issue or pull request on the GitHub repository.

# Contact

If you have any questions or concerns, please contact github@john.pub

# License

This project is licensed under the Unlicense - see the [LICENSE](LICENSE) file for details.
