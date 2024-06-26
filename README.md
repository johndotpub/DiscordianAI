<a href="https://github.com/johndotpub/DiscordianAI"><img alt="GitHub Stars" src="https://badgen.net/github/stars/johndotpub/DiscordianAI?icon=github" /></a> [![Flake8 and Pytest](https://github.com/johndotpub/DiscordianAI/actions/workflows/flake8-pytest.yml/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/flake8-pytest.yml) [![CodeQL](https://github.com/johndotpub/DiscordianAI/actions/workflows/github-code-scanning/codeql/badge.svg?branch=main)](https://github.com/johndotpub/DiscordianAI/actions/workflows/github-code-scanning/codeql) [![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](http://unlicense.org/)

# Description

This is a Python script for a Discord bot that uses OpenAI's GPT API to generate responses to user messages. The bot can be configured to listen to specific channels and respond to direct messages. The bot also has a rate limit to prevent spamming and can maintain a per user conversational history to improve response quality which is only limited by the `GPT_TOKENS` value.

# Requirements

- Bash
- Python 3.12 or Higher
- Python Modules
  - discord.py
  - openai

# Installation

1. Clone the repository to your local machine.
2. Install the required packages using pip: `pip install -r requirements.txt`
3. Rename `config.ini.example` to `config.ini` and fill in the required configuration details.

# Usage

To start the bot, run the following command:

```bash
python bot.py --conf config.ini
```

The bot will log in to Discord and start listening for messages in the configured channels. When a message is received, the bot will send the message to the OpenAI API and wait for a response. The response will be sent back to the user who sent the message.

## Detailed Documentation

For more in-depth information about the DiscordianAI project, please refer to the following documentation files in the `docs/` directory:

- [Configuration](./docs/Configuration.md) : Detailed instructions on how to configure the Discord bot and OpenAI GPT API settings.
- [Daemon](./docs/Daemon.md) : Information on how to run the Discord bot as a daemon.
- [Docker](./docs/Docker.md) : Instructions on how to containerize the Discord bot using Docker.
- [OpenAI](./docs/OpenAI.md) : Information on how the Discord bot uses the OpenAI GPT API to generate responses.
- [Setup](./docs/Setup.md) : Step-by-step guide on how to set up and run the Discord bot.

Please ensure to read through these documents to understand how to effectively use and manage the DiscordianAI bot.

# Contributing

Contributions are welcome! Please open an issue or pull request on the GitHub repository.

# Contact

If you have any questions or concerns, please contact github@john.pub

# License

This project is licensed under the Unlicense - see the [LICENSE](LICENSE) file for details.
