# Discord Bot Setup

To use this bot, you will need to create a Discord bot and invite it to your server. Here are the steps to do so:

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create a new application.
2. Click on the "Bot" tab and then click "Add Bot".
3. Copy the bot token and paste it into the `DISCORD_TOKEN` field in the `config.ini` file.
4. Under the "OAuth2" tab, select the "bot" scope and then select the permissions you want the bot to have.
5. Copy the generated OAuth2 URL and paste it into your web browser. This will allow you to invite the bot to your server.

## Running the Bot

To start the bot, use:

```bash
python -m src.main --conf config.ini --folder /path/to/base/folder
```

- `--conf`: Path to the configuration file (relative to base folder if --folder is used).
- `--folder`: (Optional) Base folder for config and logs. If provided, config and log file paths are resolved relative to this folder unless absolute.

A global exception handler is set up to log any unhandled exceptions, ensuring robust error reporting and easier debugging.