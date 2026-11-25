# Daemon Control Script

`discordian.sh` is a bash launcher for DiscordianAI that handles Python environment resolution, dependency verification, and process management. It works for manual execution, cron scheduling, and systemd services.

## Features

- **Automatic Python resolution**: Finds the right Python interpreter via project venv → shell venv → pyenv → system path (the project venv is preferred when its dependencies are present)
- **Venv bootstrapping**: Creates and populates a project-local `.venv/` if one doesn't exist
- **Correct working directory**: Always changes to the project root, so `python -m src.main --conf <file>` works regardless of where the script is invoked from (including cron's `$HOME`)
- **Process management**: Stops previous instances before starting, with graceful shutdown and forced kill fallback
- **Daemon and foreground modes**: Background mode for cron, foreground mode for systemd
- **Startup health check**: In daemon mode, waits 3 seconds and confirms the process survived
- **systemd installation**: `--install-systemd bot.ini` generates a ready-to-run user service unit, installs it, enables it, and starts it, with all paths auto-detected

## Requirements

- **Python 3.12 or newer** (project requirement)
- Bash 4+ (for `set -euo pipefail`, `[[ ]]` conditionals)
- `pgrep` for process management (available on most Linux/macOS systems)

## Python Resolution Order

The launcher resolves the Python interpreter in this priority:

1. **Project-local venv** — `.venv/bin/python3` in the project directory, used when its core dependencies are importable
2. **Shell-activated venv** — `$VIRTUAL_ENV/bin/python3` if a venv is active
3. **pyenv** — Whatever `pyenv which python3` resolves for the project directory
4. **System python3** — First `python3` on `PATH`

If no venv exists, the launcher creates one automatically using the resolved Python interpreter and installs dependencies from `requirements.txt` (or `pyproject.toml` if no requirements file exists).

> **Tip**: The project venv is preferred because it is the environment this checkout was bootstrapped with. If you use pyenv, set a project Python with `pyenv local 3.12.x`; the launcher uses it when no usable project venv exists. You can also create a project venv with `pyenv exec python -m venv .venv` to pin the interpreter.

## Usage

```bash
# Foreground (manual, systemd)
./discordian.sh -c config.ini

# Daemon mode (cron, background)
./discordian.sh -d -c config.ini

# Specify project directory explicitly
./discordian.sh -d -c production.ini -f /opt/discordianai

# Install, enable, and start a systemd user service
./discordian.sh --install-systemd bot.ini
```

### Options

| Flag | Long form | Description |
|------|-----------|-------------|
| `-d` | `--daemon` | Run in background, redirect output to `bot.log` |
| `-c` | `--config` | Configuration file (default: `bot.ini`) |
| `-f` | `--folder` | Project directory (default: script location) |
| | `--install-systemd` | Generate, install, enable, and start a systemd user service for the given config file, then exit |
| `-h` | `--help` | Show usage information |

## Running with Cron

For daily restarts, add a cron entry that runs the launcher in daemon mode:

```bash
# Restart the bot daily at 4:00 AM
0 4 * * * /path/to/DiscordianAI/discordian.sh -d -c bot.ini -f /path/to/DiscordianAI
```

The `-d` flag runs the bot in the background with output sent to `bot.log` in the project directory. The `-f` flag ensures the working directory is set correctly regardless of cron's `$HOME` default.

> **Important**: Cron environments have minimal `PATH`. If you use pyenv or Homebrew Python, make sure your `PATH` is set in the crontab or in a wrapper script. The launcher checks pyenv automatically, but pyenv must be on `PATH` for `command -v pyenv` to find it.

## Running with systemd

### Quick setup (recommended)

The launcher can generate and install a systemd user service automatically:

```bash
./discordian.sh --install-systemd bot.ini
```

This command:

1. Derives the instance name from the config file (`bot.ini` → `discordian-bot@bot`)
2. Auto-detects paths from the script's location
3. Builds a `PATH` that includes pyenv and Homebrew (detects `brew --prefix` automatically)
4. Writes the unit file to `~/.config/systemd/user/`
5. Runs `daemon-reload`, enables the service, and starts it
6. Prints management commands

The config file name (without `.ini`) becomes the systemd instance name. `--install-systemd bot.ini` creates `discordian-bot@bot.service`, `--install-systemd production.ini` creates `discordian-bot@production.service`.

### Manual setup

A template unit file is included in `contrib/systemd/discordian-bot@.service`. To install manually:

1. **Copy** the template to your systemd user directory:
   ```bash
   mkdir -p ~/.config/systemd/user
   cp contrib/systemd/discordian-bot@.service ~/.config/systemd/user/
   ```

2. **Edit the copy** — replace all `/path/to/DiscordianAI` with your actual installation path, and adjust `PATH` to include pyenv or Homebrew if needed (the `--install-systemd` flag does this automatically)

3. **Reload and enable**:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now discordian-bot@bot
   ```

### Advantages over cron

| Feature | Cron | Systemd |
|---------|------|---------|
| Auto-restart on crash | ❌ | ✅ (`Restart=on-failure`) |
| Restart delay | ✗ | ✅ (`RestartSec=15`) |
| Proper logging | File only | File (`StandardOutput=append:`); journald only if you change the unit |
| Service management | `crontab -e` | `systemctl --user` |
| Startup ordering | ✗ | ✅ (`After=network-online.target`) |

### Switching from cron to systemd

1. **Remove** the cron entry: `crontab -e` and delete the DiscordianAI line
2. **Install** the systemd service: `./discordian.sh --install-systemd bot.ini`
3. Done. The service starts and enables automatically.

Both methods can coexist, but that would start two instances. Pick one.

## Log rotation

The bot never writes its own log file; `discordian.sh -d` and the systemd unit redirect stdout and stderr to `bot.log`. Because that file stays open for the lifetime of the process, logrotate must use `copytruncate` instead of asking the bot to reopen it. The shipped fragment in `contrib/logrotate/discordianai` does this. Container deployments do not use logrotate for container output: the compose file bounds Docker's `json-file` driver at three 10 MB files instead, as described in [Docker.md](Docker.md).

Install it system-wide:

```bash
sudo cp contrib/logrotate/discordianai /etc/logrotate.d/discordianai
```

Then edit `/etc/logrotate.d/discordianai`: replace `/path/to/DiscordianAI/bot.log` with the actual log path, and replace `USER` and `GROUP` in the `su` line with the account and group that own the log directory. The `su` directive is required when the log's parent directory is world-writable or group-writable by a group other than root; without it logrotate refuses with "parent directory has insecure permissions". The fragment rotates at 100 MB, keeps fifty generations, stamps each rotated file with its date (`bot.log-2026-10-30.gz`), enables `copytruncate`, and uses `delaycompress` so the newest rotation stays uncompressed.

**Retention:** `rotate 50` keeps fifty rotated files, each about 100 MB when it is rotated. `size` is checked only when logrotate runs, so the live file is roughly 100 MB plus the growth since the previous check (with a daily check, about one day's growth). The pre-compression ceiling is therefore about 5 GB of archives plus the live file; compressed rotations are smaller, and `delaycompress` leaves the newest rotation uncompressed. At this bot's volume that is years of history. Rotation archives; it does not expire. The only setting that deletes anything is `rotate`, so lower that number deliberately if you ever want a hard ceiling. Compressed rotations are written beside the live file.

> **`copytruncate` caveat**: logrotate copies `bot.log` and then truncates the original so the running process can keep writing to the same file descriptor. Any log lines written between the copy and the truncate can be lost. This is the only option here because the supervisor owns the open file and the bot cannot be signalled to reopen it. Keep the log and its rotated copies on the same filesystem so the copy window is as short as possible.

Check the configuration without rotating anything:

```bash
sudo logrotate --debug /etc/logrotate.d/discordianai
```

For non-systemd installs, use the same fragment with a plain shell redirect. For example, start the bot in the background:

```bash
nohup .venv/bin/python -m src.main --conf bot.ini >> bot.log 2>&1 &
```

Point the fragment at that `bot.log`, install it as above, and logrotate will rotate the file the same way. `./discordian.sh -d -c bot.ini` already performs this redirect for you.

## Process Management

The launcher tracks each config's bot PID in `.bot-<stem>-<hash>.pid`, where the
short hash comes from the resolved absolute config path. Two configs that share a
basename in different directories therefore keep separate files. The launcher uses
the file for clean shutdown:

1. If the instance's PID file exists and its process still runs the same config, it
   sends `SIGTERM` and waits up to 10 seconds (override with
   `DISCORDIANAI_STOP_TIMEOUT`). A PID file whose process now runs a different config
   is removed without a signal.
2. If the process doesn't stop, it sends `SIGKILL`
3. It removes the PID file, including when the recorded process had already exited
4. It scans for stray processes started with the same resolved config file

The straggler scan resolves each process's `--conf` argument against that process's
working directory and compares it with this instance's absolute config path. Another
config in the same checkout is a separate managed instance and is left alone, and a
second checkout that also uses `bot.ini` is not mistaken for this one. On upgrade, a
legacy `.bot.pid` is honoured only when its process runs the same config; a legacy PID
belonging to another config is left in place.

One instance per config is enforced for launches the launcher owns. One instance per
Discord token is still the operator's rule: the Python process does not lock the token,
so containers, systemd, or other supervisors that bypass the launcher must enforce it
externally. Running two configs that use the same token would give it two gateway
sessions and duplicate replies.

## Venv Details

The project-local `.venv/` directory is created automatically on first run if it doesn't exist. It's excluded from git via `.gitignore`.

To recreate the venv (e.g., after a Python version change):

```bash
rm -rf .venv
./discordian.sh -c config.ini   # Will bootstrap a fresh venv
```

To force a specific Python version for the venv:

```bash
# With pyenv (optional — version-pinned, reproducible)
pyenv install 3.12.12
pyenv local 3.12.12
rm -rf .venv
./discordian.sh -c config.ini   # Will bootstrap the venv with pyenv's Python

# Without pyenv — create venv manually
/usr/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
./discordian.sh -c config.ini
```

## Troubleshooting

**"No python3 found"**
- Install Python 3.12+ or create a venv manually
- If using pyenv, ensure `pyenv` is on `PATH` (add to `~/.bashrc` or crontab)

**"Python 3.12+ required"**
- The resolved Python is too old. Check which one the launcher found:
  ```bash
  ./discordian.sh -c config.ini 2>&1 | head -5
  ```
- Install a newer Python or point pyenv to 3.12+

**"Missing core dependencies"**
- Repair the venv:
  ```bash
  .venv/bin/pip install -r requirements.txt
  ```
- Or delete and let the launcher recreate:
  ```bash
  rm -rf .venv && ./discordian.sh -c config.ini
  ```

**"Bot crashed on startup"**
- Check `bot.log` for the error
- Common causes: invalid config, missing API keys, network issues

**Wrong Python being used**
- The launcher prints which Python it resolved at startup
- Check the resolution order (project venv → shell venv → pyenv → system) and ensure your preferred Python is first

**systemd service won't start**
- Check status: `systemctl --user status discordian-bot@bot`
- Check the bot's own output in `bot.log` (`tail -f /path/to/DiscordianAI/bot.log`); `journalctl --user -u discordian-bot@bot` shows unit lifecycle messages because the shipped unit appends stdout/stderr to that file
- Verify paths in the unit file match your installation
- Re-generate with `./discordian.sh --install-systemd bot.ini` to auto-detect paths
