[![Flake8 and Pytest](https://github.com/johndotpub/DiscordianAI/actions/workflows/flake8-pytest.yml/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/flake8-pytest.yml) [![CodeQL](https://github.com/johndotpub/DiscordianAI/actions/workflows/github-code-scanning/codeql/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/github-code-scanning/codeql) [![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](http://unlicense.org/)

# Description

This is a Python script for a Discord bot that uses either OpenAI's GPT API, or any compatible API such as Perplexity to generate responses to user messages. The bot can be configured to listen to specific channels and respond to direct messages. The bot also has a rate limit to prevent spamming and can maintain a per user conversational history to improve response quality which is only limited by the `GPT_TOKENS` value.

# Requirements

- Bash
- Python 3.12 or Higher
- Python Modules
  - discord.py
  - openai

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

The `config.ini` file contains the following configuration sections:

### Discord

- `DISCORD_TOKEN`: The Discord bot token.
- `ALLOWED_CHANNELS`: A comma-separated list of channel names that the bot is allowed to listen to.
- `BOT_PRESENCE`: The presence of the bot (e.g. online, offline, idle).
- `ACTIVITY_TYPE`: The type of activity for the bot (e.g. playing, streaming, listening, watching, custom, competing).
- `ACTIVITY_STATUS`: The activity status of the bot (e.g. Humans).

### Default Configs

- `API_URL`: The backend API URL. (default: `https://api.openai.com/v1/`)
- `API_KEY`: The API key for your backend. (default: `None`)
- `GPT_MODEL`: The GPT model to use (default: `gpt-4o-mini`)
- `INPUT_TOKENS`: Your response input size. (default: `120000`)
- `OUTPUT_TOKENS`: The maximum number of tokens to generate in the GPT response (default: `8000`)
- `CONTEXT_WINDOW`: The maximum number of tokens to keep in the context window. (default: `128000`)
- `SYSTEM_MESSAGE`: The message to send to the GPT model before the user's message.

### Limits

- `RATE_LIMIT`: The number of messages a user can send within `RATE_LIMIT_PER` seconds (default: `2`).
- `RATE_LIMIT_PER`: The time period in seconds for the rate limit (default: `10`).

### Logging

- `LOG_FILE`: The path to the log file (default: bot.log).

Here is an example `config.ini` file:

```ini
[Discord]
DISCORD_TOKEN = <your_discord_bot_token>
ALLOWED_CHANNELS = <allowed_channel_id_1>, <allowed_channel_id_2>, ...
BOT_PRESENCE = online
# ACTIVITY_TYPE Options
# playing, streaming, listening, watching, custom, competing
ACTIVITY_TYPE=listening
ACTIVITY_STATUS=Humans

[Default]
API_URL=https://api.openai.com/v1/
API_KEY = <your_api_key>
GPT_MODEL=gpt-4o-mini
INPUT_TOKENS=120000
OUTPUT_TOKENS=8000
CONTEXT_WINDOW=128000
SYSTEM_MESSAGE = You are a helpful AI assistant.

[Limits]
RATE_LIMIT = 2
RATE_LIMIT_PER = 10

[Logging]
LOG_FILE = bot.log
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

- [Configuration](./docs/Configuration.md) : Detailed instructions on how to configure the Discord bot and OpenAI GPT API settings.
- [Daemon](./docs/Daemon.md) : Information on how to run the Discord bot as a daemon.
- [Docker](./docs/Docker.md) : Instructions on how to containerize the Discord bot using Docker.
- [OpenAI](./docs/OpenAI.md) : Information on how the Discord bot uses the OpenAI GPT API to generate responses.
- [Setup](./docs/Setup.md) : Step-by-step guide on how to set up and run the Discord bot.

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
