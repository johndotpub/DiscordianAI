#!/usr/bin/env bash
# DiscordianAI Launcher — portable, venv-aware, pyenv-friendly
#
# Suitable for manual execution, crontab, or systemd (foreground mode).
# Always changes directory to the project root before launching,
# so Python can find the `src` package regardless of how it's invoked.
#
# Usage:
#   ./discordian.sh                          # foreground, default config
#   ./discordian.sh -d                       # daemon mode (background)
#   ./discordian.sh -c bot.ini               # custom config file
#   ./discordian.sh -f /path/to/project      # project directory
#   ./discordian.sh -d -c production.ini -f /opt/discordianai
#   ./discordian.sh --install-systemd bot.ini # install and enable systemd service
#
# Python resolution order:
#   1. pyenv-managed python3 (preferred — version-pinned, reproducible)
#   2. Project-local .venv/bin/python3
#   3. Shell-activated venv ($VIRTUAL_ENV)
#   4. System python3
#
# If no venv exists, one is created automatically in the project directory.

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
CONFIG_FILE="bot.ini"
DAEMON_MODE=false
PROJECT_DIR="${SCRIPT_DIR}"
INSTALL_SYSTEMD=""

# ── Argument parsing ──────────────────────────────────────────────────
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -d|--daemon) DAEMON_MODE=true; shift ;;
        -c|--config)
            [[ -n "${2:-}" && ! "$2" =~ ^- ]] || { echo "ERROR: -c requires a config file argument" >&2; exit 1; }
            CONFIG_FILE="$2"; shift 2 ;;
        -f|--folder)
            [[ -n "${2:-}" && ! "$2" =~ ^- ]] || { echo "ERROR: -f requires a directory argument" >&2; exit 1; }
            PROJECT_DIR="$(realpath "$2")"; shift 2 ;;
        --install-systemd)
            [[ -n "${2:-}" && ! "$2" =~ ^- ]] || { echo "ERROR: --install-systemd requires a config file argument" >&2; exit 1; }
            INSTALL_SYSTEMD="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [-d] [-c config.ini] [-f /path/to/project]"
            echo "       $0 --install-systemd config.ini"
            echo ""
            echo "  -d, --daemon            Run in background (daemon mode)"
            echo "  -c, --config            Configuration file (default: bot.ini)"
            echo "  -f, --folder            Project directory (default: script location)"
            echo "      --install-systemd   Generate and install a systemd user service for"
            echo "                          the given config file, then exit"
            echo "  -h, --help              Show this help message"
            exit 0 ;;
        *) shift ;;
    esac
done

VENV_DIR="${PROJECT_DIR}/.venv"
PID_FILE="${PROJECT_DIR}/.bot.pid"
LOG_FILE="${PROJECT_DIR}/bot.log"

# ── systemd installation ─────────────────────────────────────────────
#     Generates a unit file from the config file name and installs it.
#     The config file (e.g. bot.ini) becomes the systemd instance name
#     (discordian-bot@bot). All paths are resolved from the script location.
if [[ -n "${INSTALL_SYSTEMD}" ]]; then
    # Derive instance name from config file (bot.ini → bot)
    INSTANCE="$(basename "${INSTALL_SYSTEMD}" .ini)"
    CONFIG_FILE="${INSTALL_SYSTEMD}"
    UNIT_NAME="discordian-bot@${INSTANCE}.service"
    UNIT_DIR="${HOME}/.config/systemd/user"
    UNIT_FILE="${UNIT_DIR}/${UNIT_NAME}"

    # Verify config exists
    CONFIG_PATH="${PROJECT_DIR}/${CONFIG_FILE}"
    if [[ ! -f "${CONFIG_PATH}" ]]; then
        echo "ERROR: Config file not found: ${CONFIG_PATH}" >&2
        exit 1
    fi

    # Build PATH env for the systemd unit — detect pyenv and homebrew dynamically
    UNIT_PATH=""
    # pyenv
    [[ -d "${HOME}/.pyenv/shims" ]] && UNIT_PATH="${HOME}/.pyenv/shims:"
    [[ -d "${HOME}/.pyenv/bin" ]] && UNIT_PATH="${UNIT_PATH}${HOME}/.pyenv/bin:"
    # Homebrew — detect prefix from brew if available, else check standard locations
    if command -v brew >/dev/null 2>&1; then
        BREW_PREFIX="$(brew --prefix 2>/dev/null)"
        if [[ -n "${BREW_PREFIX}" && -d "${BREW_PREFIX}/bin" ]]; then
            UNIT_PATH="${UNIT_PATH}${BREW_PREFIX}/bin:${BREW_PREFIX}/sbin:"
        fi
    else
        # Fallback: check standard Homebrew locations
        for brew_dir in /home/linuxbrew/.linuxbrew /opt/homebrew "/usr/local/Homebrew" "${HOME}/.linuxbrew"; do
            if [[ -d "${brew_dir}/bin" ]]; then
                UNIT_PATH="${UNIT_PATH}${brew_dir}/bin:${brew_dir}/sbin:"
            fi
        done
    fi
    UNIT_PATH="${UNIT_PATH}/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    mkdir -p "${UNIT_DIR}"
    cat > "${UNIT_FILE}" <<EOF
[Unit]
Description=DiscordianAI Bot (${INSTANCE})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${SCRIPT_DIR}/discordian.sh -c ${CONFIG_FILE} -f ${PROJECT_DIR}
WorkingDirectory=${PROJECT_DIR}
Restart=on-failure
RestartSec=15

StandardOutput=append:${PROJECT_DIR}/bot.log
StandardError=append:${PROJECT_DIR}/bot.log

Environment=PATH=${UNIT_PATH}
Environment=HOME=${HOME}
Environment=LANG=en_US.UTF-8

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${PROJECT_DIR}

[Install]
WantedBy=default.target
EOF

    echo "Generated: ${UNIT_FILE}"
    systemctl --user daemon-reload
    systemctl --user enable "${UNIT_NAME}"
    echo ""
    echo "Service installed and enabled. Manage with:"
    echo "  systemctl --user start ${UNIT_NAME}"
    echo "  systemctl --user status ${UNIT_NAME}"
    echo "  journalctl --user -u ${UNIT_NAME} -f"
    echo ""
    echo "To uninstall:"
    echo "  systemctl --user disable ${UNIT_NAME}"
    echo "  rm ${UNIT_FILE}"
    echo "  systemctl --user daemon-reload"
    exit 0
fi

# ── Logging ───────────────────────────────────────────────────────────
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }

# ── 1. Change to project directory ────────────────────────────────────
#     Cron runs from $HOME — Python needs CWD inside the project to
#     find the `src` package via `-m src.main`.
cd "${PROJECT_DIR}"
log "Working directory: $(pwd)"

# ── 2. Resolve Python interpreter ─────────────────────────────────────
#     Priority: pyenv → project venv → shell venv → system python3
resolve_python() {
    # pyenv first — version-pinned, reproducible
    if command -v pyenv >/dev/null 2>&1; then
        local pyenv_python
        pyenv_python="$(pyenv which python3 2>/dev/null || true)"
        if [[ -n "${pyenv_python}" && -x "${pyenv_python}" ]]; then
            echo "${pyenv_python}"
            return 0
        fi
    fi
    # Project-local venv
    if [[ -x "${VENV_DIR}/bin/python3" ]]; then
        echo "${VENV_DIR}/bin/python3"
        return 0
    fi
    # Shell-activated venv (VIRTUAL_ENV is set)
    if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python3" ]]; then
        echo "${VIRTUAL_ENV}/bin/python3"
        return 0
    fi
    # System python3
    local sys_python
    sys_python="$(command -v python3 2>/dev/null || true)"
    if [[ -n "${sys_python}" ]]; then
        echo "${sys_python}"
        return 0
    fi
    return 1
}

PYTHON="$(resolve_python)" || {
    log "ERROR: No python3 found. Install Python 3.12+ or create a venv."
    exit 1
}
log "Using python3: ${PYTHON} ($(${PYTHON} --version 2>&1))"

# ── 3. Verify Python version (3.12+) ──────────────────────────────────
py_major="$(${PYTHON} -c 'import sys; print(sys.version_info[0])')"
py_minor="$(${PYTHON} -c 'import sys; print(sys.version_info[1])')"
if [[ "${py_major}" -lt 3 ]] || [[ "${py_major}" -eq 3 && "${py_minor}" -lt 12 ]]; then
    log "ERROR: Python 3.12+ required, found ${py_major}.${py_minor}"
    exit 1
fi

# ── 4. Bootstrap venv if missing ──────────────────────────────────────
if [[ ! -d "${VENV_DIR}" || ! -x "${VENV_DIR}/bin/python3" ]]; then
    log "Creating venv at ${VENV_DIR} using ${PYTHON}..."
    "${PYTHON}" -m venv "${VENV_DIR}" || {
        log "ERROR: Failed to create venv. Check Python installation."
        exit 1
    }
    log "Installing dependencies..."
    if [[ -f "${PROJECT_DIR}/requirements.txt" ]]; then
        "${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt" --quiet 2>/dev/null || {
            log "WARNING: pip install reported issues, retrying with verbose output..."
            "${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"
        }
    elif [[ -f "${PROJECT_DIR}/pyproject.toml" ]]; then
        "${VENV_DIR}/bin/pip" install -e "${PROJECT_DIR}" --quiet 2>/dev/null || {
            log "WARNING: pip install reported issues, retrying with verbose output..."
            "${VENV_DIR}/bin/pip" install -e "${PROJECT_DIR}"
        }
    else
        log "WARNING: No requirements.txt or pyproject.toml found — dependencies may be missing."
    fi
    log "Venv bootstrapped successfully."
    # Re-resolve to the venv python
    PYTHON="${VENV_DIR}/bin/python3"
fi

# ── 5. Dependency check ───────────────────────────────────────────────
log "Checking core dependencies..."
if ! "${PYTHON}" -c "import discord; import openai; import httpx" 2>/dev/null; then
    log "ERROR: Missing core dependencies (discord.py, openai, or httpx)."
    log "Repair with: ${VENV_DIR}/bin/pip install -r requirements.txt"
    exit 1
fi
log "✓ All core dependencies available"

# ── 6. Kill existing instances (cron restart) ──────────────────────────
log "Stopping any existing instances..."
my_pid="$$"

# By PID file
if [[ -f "${PID_FILE}" ]]; then
    old_pid="$(cat "${PID_FILE}")"
    if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
        log "Stopping previous instance (PID ${old_pid})"
        kill "${old_pid}" 2>/dev/null || true
        local_wait=0
        while kill -0 "${old_pid}" 2>/dev/null && [[ ${local_wait} -lt 10 ]]; do
            sleep 1; ((local_wait++))
        done
        if kill -0 "${old_pid}" 2>/dev/null; then
            log "Force-killing unresponsive process ${old_pid}"
            kill -9 "${old_pid}" 2>/dev/null || true
        fi
    fi
    rm -f "${PID_FILE}"
fi

# Stragglers matching the bot pattern (but not ourselves)
for pid in $(pgrep -f "src.main.*--conf" 2>/dev/null || true); do
    if [[ "${pid}" != "${my_pid}" ]]; then
        log "Killing stray process ${pid}"
        kill "${pid}" 2>/dev/null || true
    fi
done

# ── 7. Build and launch the command ────────────────────────────────────
CMD_ARGS=(-m src.main --conf "${CONFIG_FILE}")
if [[ "${PROJECT_DIR}" != "$(pwd)" ]]; then
    CMD_ARGS+=(--folder "${PROJECT_DIR}")
fi
log "Command: ${PYTHON} ${CMD_ARGS[*]}"

if [[ "${DAEMON_MODE}" == true ]]; then
    # ── Daemon mode: background, redirect to log file ──────────────────
    log "Daemon mode: logging to ${LOG_FILE}"
    nohup "${PYTHON}" "${CMD_ARGS[@]}" >> "${LOG_FILE}" 2>&1 &
    bot_pid=$!
    echo "${bot_pid}" > "${PID_FILE}"
    log "Bot started in background (PID ${bot_pid})"

    # Health check: give it a few seconds to crash on startup
    sleep 3
    if kill -0 "${bot_pid}" 2>/dev/null; then
        log "✓ Bot is running (PID ${bot_pid})"
    else
        log "ERROR: Bot crashed on startup. Check ${LOG_FILE}"
        rm -f "${PID_FILE}"
        exit 1
    fi
else
    # ── Foreground mode: systemd or manual ────────────────────────────
    echo "$$" > "${PID_FILE}"
    log "Running in foreground (PID $$)"
    exec "${PYTHON}" "${CMD_ARGS[@]}"
fi
