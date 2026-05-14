# Daemon Control Script

`discordian.sh` is a bash launcher for DiscordianAI that handles Python environment resolution, dependency verification, and process management. It works for manual execution, cron scheduling, and systemd services.

## Features

- **Automatic Python resolution**: Finds the right Python interpreter via pyenv → project venv → shell venv → system path (pyenv preferred for version pinning)
- **Venv bootstrapping**: Creates and populates a project-local `.venv/` if one doesn't exist
- **Correct working directory**: Always changes to the project root, so `python -m src.main` works regardless of where the script is invoked from (including cron's `$HOME`)
- **Process management**: Stops previous instances before starting, with graceful shutdown and forced kill fallback
- **Daemon and foreground modes**: Background mode for cron, foreground mode for systemd
- **Startup health check**: In daemon mode, waits 3 seconds and confirms the process survived
- **systemd installation**: `--install-systemd bot.ini` generates a ready-to-run user service unit with all paths auto-detected

## Requirements

- **Python 3.12 or newer** (project requirement)
- Bash 4+ (for `set -euo pipefail`, `[[ ]]` conditionals)
- `pgrep` for process management (available on most Linux/macOS systems)

## Python Resolution Order

The launcher resolves the Python interpreter in this priority:

1. **pyenv** — Whatever `pyenv which python3` resolves for the project directory
2. **Project-local venv** — `.venv/bin/python3` in the project directory
3. **Shell-activated venv** — `$VIRTUAL_ENV/bin/python3` if a venv is active
4. **System python3** — First `python3` on `PATH`

If no venv exists, the launcher creates one automatically using the resolved Python interpreter and installs dependencies from `requirements.txt` (or `pyproject.toml` if no requirements file exists).

> **Tip**: pyenv resolution is preferred because it's version-pinned and reproducible. If you use pyenv, set a project Python with `pyenv local 3.12.x` and the launcher will pick it up automatically. You can also create a project venv with `pyenv exec python -m venv .venv` to pin the interpreter.

## Usage

```bash
# Foreground (manual, systemd)
./discordian.sh -c config.ini

# Daemon mode (cron, background)
./discordian.sh -d -c config.ini

# Specify project directory explicitly
./discordian.sh -d -c production.ini -f /opt/discordianai

# Install and enable a systemd user service
./discordian.sh --install-systemd bot.ini
```

### Options

| Flag | Long form | Description |
|------|-----------|-------------|
| `-d` | `--daemon` | Run in background, redirect output to `bot.log` |
| `-c` | `--config` | Configuration file (default: `bot.ini`) |
| `-f` | `--folder` | Project directory (default: script location) |
| | `--install-systemd` | Generate and install a systemd user service for the given config file, then exit |
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
5. Runs `daemon-reload` and enables the service
6. Prints management commands

The config file name (without `.ini`) becomes the systemd instance name. `--install-systemd bot.ini` creates `discordian-bot@bot.service`, `--install-systemd production.ini` creates `discordian-bot@prod.service`.

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
| Proper logging | File only | `journalctl` + file |
| Service management | `crontab -e` | `systemctl --user` |
| Startup ordering | ✗ | ✅ (`After=network-online.target`) |

### Switching from cron to systemd

1. **Remove** the cron entry: `crontab -e` and delete the DiscordianAI line
2. **Install** the systemd service: `./discordian.sh --install-systemd bot.ini`
3. Done. The service starts and enables automatically.

Both methods can coexist, but that would start two instances. Pick one.

## Process Management

The launcher tracks the bot's PID in `.bot.pid` (in the project directory) and uses it for clean shutdown:

1. If a `.bot.pid` file exists, it sends `SIGTERM` and waits up to 10 seconds
2. If the process doesn't stop, it sends `SIGKILL`
3. It also scans for stray processes matching `src.main --conf`

This ensures clean restarts whether triggered by cron, systemd, or manual invocation.

## Venv Details

The project-local `.venv/` directory is created automatically on first run if it doesn't exist. It's excluded from git via `.gitignore`.

To recreate the venv (e.g., after a Python version change):

```bash
rm -rf .venv
./discordian.sh -c config.ini   # Will bootstrap a fresh venv
```

To force a specific Python version for the venv:

```bash
# With pyenv (preferred — version-pinned, reproducible)
pyenv install 3.12.12
pyenv local 3.12.12
rm -rf .venv
./discordian.sh -c config.ini   # Will use pyenv's Python automatically

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
- Check the resolution order (pyenv → venv → system) and ensure your preferred Python is first

**systemd service won't start**
- Check status: `systemctl --user status discordian-bot@bot`
- Check logs: `journalctl --user -u discordian-bot@bot -f`
- Verify paths in the unit file match your installation
- Re-generate with `./discordian.sh --install-systemd bot.ini` to auto-detect paths
