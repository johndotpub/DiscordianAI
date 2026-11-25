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
#   ./discordian.sh --install-systemd bot.ini # install, enable, start systemd service
#
# Python resolution order:
#   1. Project-local .venv/bin/python3 (preferred when its dependencies are present)
#   2. Shell-activated venv ($VIRTUAL_ENV)
#   3. pyenv-managed python3
#   4. System python3
#
# If no venv exists, one is created automatically in the project directory.

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
# shellcheck source=scripts/launcher_lib.sh
source "${SCRIPT_DIR}/scripts/launcher_lib.sh"
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
        --config=*)
            CONFIG_FILE="${1#--config=}"
            [[ -n "${CONFIG_FILE}" ]] || { echo "ERROR: --config requires a config file argument" >&2; exit 1; }
            shift ;;
        -f|--folder)
            [[ -n "${2:-}" && ! "$2" =~ ^- ]] || { echo "ERROR: -f requires a directory argument" >&2; exit 1; }
            PROJECT_DIR="$(realpath "$2")"; shift 2 ;;
        --folder=*)
            PROJECT_DIR="${1#--folder=}"
            [[ -n "${PROJECT_DIR}" ]] || { echo "ERROR: --folder requires a directory argument" >&2; exit 1; }
            PROJECT_DIR="$(realpath "${PROJECT_DIR}")"; shift ;;
        --install-systemd)
            [[ -n "${2:-}" && ! "$2" =~ ^- ]] || { echo "ERROR: --install-systemd requires a config file argument" >&2; exit 1; }
            INSTALL_SYSTEMD="$2"; shift 2 ;;
        --install-systemd=*)
            INSTALL_SYSTEMD="${1#--install-systemd=}"
            [[ -n "${INSTALL_SYSTEMD}" ]] || { echo "ERROR: --install-systemd requires a config file argument" >&2; exit 1; }
            shift ;;
        -h|--help)
            echo "Usage: $0 [-d] [-c config.ini] [-f /path/to/project]"
            echo "       $0 --install-systemd config.ini"
            echo ""
            echo "  -d, --daemon            Run in background (daemon mode)"
            echo "  -c, --config            Configuration file (default: bot.ini)"
            echo "  -f, --folder            Project directory (default: script location)"
            echo "      --install-systemd   Generate, install, enable, and start a systemd"
            echo "                          user service for the given config file, then exit"
            echo "  -h, --help              Show this help message"
            echo ""
            echo "  --config=FILE, --folder=DIR, and --install-systemd=FILE are also accepted."
            exit 0 ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            echo "Usage: $0 [-d] [-c config.ini] [-f /path/to/project]" >&2
            echo "       $0 --install-systemd config.ini" >&2
            exit 2 ;;
    esac
done

VENV_DIR="${PROJECT_DIR}/.venv"
LEGACY_PID_FILE="${PROJECT_DIR}/.bot.pid"
PID_FILE="$(instance_pid_file "${PROJECT_DIR}" "${CONFIG_FILE}")"
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

    # Verify config exists using the same resolver as the run path.
    CONFIG_PATH="$(require_config_file "${PROJECT_DIR}" "${CONFIG_FILE}")" || exit 1

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

    # systemd parses ExecStart and ReadWritePaths as word lists, but
    # WorkingDirectory, StandardOutput, and StandardError take the rest of the
    # line as a single value. Quote only the word-list directives.
    systemd_word() {
        local value="$1"
        value="${value//\\/\\\\}"
        value="${value//\"/\\\"}"
        value="${value//%/%%}"
        value="${value//\$/\$\$}"
        printf '%s' "${value}"
    }
    systemd_path() {
        local value="$1"
        value="${value//%/%%}"
        printf '%s' "${value}"
    }
    systemd_environment() {
        local name="$1"
        local value="$2"
        local escaped
        escaped="$(systemd_word "${value}")"
        if [[ "${value}" =~ [[:space:]] ]]; then
            printf '"%s=%s"' "${name}" "${escaped}"
        else
            printf '%s=%s' "${name}" "${escaped}"
        fi
    }

    EXEC_START="\"$(systemd_word "${SCRIPT_DIR}/discordian.sh")\" -c \"$(systemd_word "${CONFIG_FILE}")\" -f \"$(systemd_word "${PROJECT_DIR}")\""
    WORKING_DIRECTORY="$(systemd_path "${PROJECT_DIR}")"
    STANDARD_OUTPUT="append:$(systemd_path "${PROJECT_DIR}/bot.log")"
    READ_WRITE_PATHS="\"$(systemd_word "${PROJECT_DIR}")\""
    ENV_PATH="$(systemd_environment PATH "${UNIT_PATH}")"
    ENV_HOME="$(systemd_environment HOME "${HOME}")"
    ENV_LANG="$(systemd_environment LANG "en_US.UTF-8")"

    mkdir -p "${UNIT_DIR}"
    cat > "${UNIT_FILE}" <<EOF
[Unit]
Description=DiscordianAI Bot (${INSTANCE})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${EXEC_START}
WorkingDirectory=${WORKING_DIRECTORY}
Restart=on-failure
RestartSec=15

StandardOutput=${STANDARD_OUTPUT}
StandardError=${STANDARD_OUTPUT}

Environment=${ENV_PATH}
Environment=${ENV_HOME}
Environment=${ENV_LANG}

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${READ_WRITE_PATHS}

[Install]
WantedBy=default.target
EOF

    echo "Generated: ${UNIT_FILE}"
    systemctl --user daemon-reload
    systemctl --user enable "${UNIT_NAME}"
    if systemctl --user is-active --quiet "${UNIT_NAME}"; then
        systemctl --user restart "${UNIT_NAME}"
    else
        systemctl --user start "${UNIT_NAME}"
    fi
    echo ""
    echo "Service installed, enabled, and started (restarted when already active). Manage with:"
    echo "  systemctl --user status ${UNIT_NAME}"
    echo "  tail -f \"${PROJECT_DIR}/bot.log\""
    echo "  journalctl --user -u ${UNIT_NAME}  # unit lifecycle only"
    echo ""
    echo "To uninstall:"
    echo "  systemctl --user disable ${UNIT_NAME}"
    echo "  rm \"${UNIT_FILE}\""
    echo "  systemctl --user daemon-reload"
    exit 0
fi

# ── Logging ───────────────────────────────────────────────────────────
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }

# Refuse a missing config before any running instance is signalled.
CONFIG_PATH="$(require_config_file "${PROJECT_DIR}" "${CONFIG_FILE}")" || exit 1

# ── 1. Change to project directory ────────────────────────────────────
#     Cron runs from $HOME — Python needs CWD inside the project to
#     find the `src` package via `-m src.main`.
cd "${PROJECT_DIR}"
log "Working directory: $(pwd)"

# ── 2. Resolve Python interpreter ─────────────────────────────────────
#     Priority: project venv → shell venv → pyenv → system python3
python_has_core_dependencies() {
    "${1}" -c "import discord; import openai; import httpx" >/dev/null 2>&1
}

resolve_python() {
    # Project-local venv first — it is the environment this checkout was
    # bootstrapped with, as long as its dependencies are present.
    if [[ -x "${VENV_DIR}/bin/python3" ]] && python_has_core_dependencies "${VENV_DIR}/bin/python3"; then
        echo "${VENV_DIR}/bin/python3"
        return 0
    fi
    # Shell-activated venv (VIRTUAL_ENV is set)
    if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python3" ]]; then
        echo "${VIRTUAL_ENV}/bin/python3"
        return 0
    fi
    # pyenv — version-pinned, reproducible when the project venv is absent
    if command -v pyenv >/dev/null 2>&1; then
        local pyenv_python
        pyenv_python="$(pyenv which python3 2>/dev/null || true)"
        if [[ -n "${pyenv_python}" && -x "${pyenv_python}" ]]; then
            echo "${pyenv_python}"
            return 0
        fi
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
log "Using python3: ${PYTHON} ($("${PYTHON}" --version 2>&1))"

# ── 3. Verify Python version (3.12+) ──────────────────────────────────
py_major="$("${PYTHON}" -c 'import sys; print(sys.version_info[0])')"
py_minor="$("${PYTHON}" -c 'import sys; print(sys.version_info[1])')"
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
if ! python_has_core_dependencies "${PYTHON}"; then
    log "ERROR: Missing core dependencies (discord.py, openai, or httpx)."
    log "Repair with: ${VENV_DIR}/bin/pip install -r requirements.txt"
    exit 1
fi
log "✓ All core dependencies available"

# ── 6. Kill existing instances (cron restart) ──────────────────────────
log "Stopping any existing instances..."
my_pid="$$"

# The legacy shared file is used only when it records this same config.
stop_legacy_pid_file_instance "${LEGACY_PID_FILE}" "${CONFIG_PATH}"

# By this config's PID file. The helper removes the file even when the process
# already died.
stop_pid_file_instance "${PID_FILE}" "${CONFIG_PATH}"

# Stragglers for this config only (but not ourselves). A different config's
# instance is a different managed service and must keep running. Each straggler
# gets the same bounded wait as the PID-file path before a new bot starts.
for pid in $(straggler_pids "${CONFIG_PATH}"); do
    if [[ "${pid}" != "${my_pid}" ]]; then
        log "Killing stray process ${pid} for ${CONFIG_PATH}"
        terminate_process "${pid}"
    fi
done

# ── 7. Build and launch the command ────────────────────────────────────
CMD_ARGS=(-m src.main --conf "${CONFIG_PATH}")
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
