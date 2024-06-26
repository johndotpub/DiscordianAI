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
- `OPENAI_TIMEOUT`: The OpenAI API timeout in seconds. (default: `30`)
- `GPT_MODEL`: The GPT model to use (default: `gpt-3.5-turbo`).
- `GPT_TOKENS`: The maximum number of tokens to generate in the GPT response (default: `3072`).
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