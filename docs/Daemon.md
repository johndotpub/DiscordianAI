# Daemon Control Script

`discordian.sh` is a bash script for launching a DiscordianAI bot with customizable configurations. It is suitable for both manual execution and running via crontab.

### Features

- Strict error checking: The script exits on any error and recognizes failures in pipelines.
- Logging: The script logs events with timestamps for better tracking.
- Customizable configurations: The script allows for different modes of operation and configurations.
- Error Handling: It logs errors and exits on failure.
- Process Handling: It terminates existing instances of the bot before starting a new one.

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

> **Note:** Daemon/background mode is handled by the `discordian.sh` shell script, which supports `-d/--daemon`, `-c/--config`, and `-f/--folder` arguments. The Python code now supports `--folder` for base directory resolution of config and log files.