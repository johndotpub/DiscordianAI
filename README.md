<a href="https://github.com/rlywtf/DiscordianAI"><img alt="GitHub Stars" src="https://badgen.net/github/stars/rlywtf/DiscordianAI?icon=github" /></a> [![CodeQL](https://github.com/rlywtf/DiscordianAI/actions/workflows/github-code-scanning/codeql/badge.svg?branch=main)](https://github.com/rlywtf/DiscordianAI/actions/workflows/github-code-scanning/codeql) [![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](http://unlicense.org/)

# Description

This is a Python script for a Discord bot that uses OpenAI's GPT API to generate responses to user messages. The bot can be configured to listen to specific channels and respond to direct messages. The bot also has a rate limit to prevent spamming and can maintain a per user conversational history to improve response quality which is only limited by the `GPT_TOKENS` value.

# Requirements

- Python 3.6 or higher
- discord.py
- openai

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

### OpenAI

- `OPENAI_API_KEY`: The OpenAI API key.
- `OPENAI_TIMEOUT`: The OpenAI API timeout in seconds. (default: 30)
- `GPT_MODEL`: The GPT model to use (default: gpt-3.5-turbo).
- `GPT_TOKENS`: The maximum number of tokens to generate in the GPT response (default: 3072).
- `SYSTEM_MESSAGE`: The message to send to the GPT model before the user's message.

### Limits

- `RATE_LIMIT`: The number of messages a user can send within `RATE_LIMIT_PER` seconds (default: 2).
- `RATE_LIMIT_PER`: The time period in seconds for the rate limit (default: 10).

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

[OpenAI]
OPENAI_API_KEY = <your_openai_api_key>
OPENAI_TIMEOUT=30
GPT_MODEL=gpt-3.5-turbo
GPT_TOKENS=3072
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

```
python bot.py --conf config.ini
```

The bot will log in to Discord and start listening for messages in the configured channels. When a message is received, the bot will send the message to the OpenAI API and wait for a response. The response will be sent back to the user who sent the message.

# Contributing

Contributions are welcome! Please open an issue or pull request on the GitHub repository.

# Contact

If you have any questions or concerns, please contact us at code@rly.wtf

# License

This project is licensed under the Unlicense - see the [LICENSE](LICENSE) file for details.
