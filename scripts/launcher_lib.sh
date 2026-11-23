#!/usr/bin/env bash
# Process-management helpers for discordian.sh.
#
# This file is sourced, not executed. Tests source it directly so the wait
# loop, PID-file cleanup, and straggler matching can be exercised without
# starting the bot.

if ! declare -F log >/dev/null 2>&1; then
    log() { printf '[launcher] %s\n' "$1" >&2; }
fi

# Wait up to timeout seconds for the process to exit. The caller checks
# liveness afterwards; this returns successfully even when the timeout expires.
wait_for_exit() {
    local pid="$1"
    local timeout="${2:-10}"
    local waited=0

    while kill -0 "${pid}" 2>/dev/null && [[ "${waited}" -lt "${timeout}" ]]; do
        sleep 1
        waited=$((waited + 1))
    done
}

# Stop the instance recorded in a PID file, then always remove the file.
stop_pid_file_instance() {
    local pid_file="$1"

    if [[ ! -f "${pid_file}" ]]; then
        return 0
    fi

    local old_pid
    old_pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
        log "Stopping previous instance (PID ${old_pid})"
        kill "${old_pid}" 2>/dev/null || true
        wait_for_exit "${old_pid}" 10
        if kill -0 "${old_pid}" 2>/dev/null; then
            log "Force-killing unresponsive process ${old_pid}"
            kill -9 "${old_pid}" 2>/dev/null || true
        fi
    fi
    rm -f "${pid_file}"
}

# Escape a string for use as an extended regular expression.
escape_ere() {
    printf '%s' "$1" | sed 's/[][\\.^$*+?(){}|]/\\&/g'
}

# Return the PIDs of bot processes started with this exact config file.
straggler_pids() {
    local config_file="$1"
    local pattern

    pattern="src\\.main.*--conf[[:space:]]+$(escape_ere "${config_file}")([[:space:]]|\$)"
    pgrep -f -- "${pattern}" 2>/dev/null || true
}
