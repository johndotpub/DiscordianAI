#!/usr/bin/env bash
# Process-management helpers for discordian.sh.
#
# This file is sourced, not executed. Tests source it directly so the wait
# loop, PID-file cleanup, and straggler matching can be exercised without
# starting the bot.

if ! declare -F log >/dev/null 2>&1; then
    log() { printf '[launcher] %s\n' "$1" >&2; }
fi

# Resolve a config path to the absolute path that identifies one instance.
resolve_config_path() {
    local project_dir="$1"
    local config_file="$2"
    local candidate

    if [[ "${config_file}" = /* ]]; then
        candidate="${config_file}"
    else
        candidate="${project_dir}/${config_file}"
    fi
    realpath -m -- "${candidate}" 2>/dev/null || realpath -- "${candidate}" 2>/dev/null || printf '%s\n' "${candidate}"
}

# PID file for one config, derived from its file stem.
instance_pid_file() {
    local project_dir="$1"
    local config_file="$2"
    local stem

    stem="$(basename -- "${config_file}")"
    stem="${stem%.ini}"
    printf '%s/.bot-%s.pid\n' "${project_dir}" "${stem}"
}

# Command line of a running process, or an empty string when it is gone.
process_command_line() {
    local pid="$1"

    if [[ -r "/proc/${pid}/cmdline" ]]; then
        tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true
    else
        ps -o args= -p "${pid}" 2>/dev/null || true
    fi
}

# Working directory of a running process, or an empty string when unknown.
process_working_directory() {
    local pid="$1"

    if [[ -e "/proc/${pid}/cwd" ]]; then
        readlink -f -- "/proc/${pid}/cwd" 2>/dev/null || true
    else
        lsof -a -p "${pid}" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true
    fi
}

# True when the process was started with this exact config file. A relative
# --conf value is resolved against the process's own working directory.
process_uses_config() {
    local pid="$1"
    local expected_config="$2"
    local cmdline conf_arg cwd resolved

    cmdline="$(process_command_line "${pid}")"
    [[ -n "${cmdline}" ]] || return 1

    conf_arg="$(printf '%s\n' "${cmdline}" | sed -n 's/.*--conf[[:space:]][[:space:]]*\([^[:space:]]*\).*/\1/p' | head -n 1)"
    [[ -n "${conf_arg}" ]] || return 1

    if [[ "${conf_arg}" = /* ]]; then
        resolved="$(realpath -m -- "${conf_arg}" 2>/dev/null || realpath -- "${conf_arg}" 2>/dev/null || printf '%s' "${conf_arg}")"
    else
        cwd="$(process_working_directory "${pid}")"
        [[ -n "${cwd}" ]] || return 1
        resolved="$(realpath -m -- "${cwd}/${conf_arg}" 2>/dev/null || realpath -- "${cwd}/${conf_arg}" 2>/dev/null || printf '%s' "${cwd}/${conf_arg}")"
    fi

    [[ "${resolved}" == "${expected_config}" ]]
}

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

# Stop the pre-fix .bot.pid instance only when it records this config.
# A legacy PID that belongs to another config is left untouched.
stop_legacy_pid_file_instance() {
    local pid_file="$1"
    local expected_config="$2"
    local old_pid

    if [[ ! -f "${pid_file}" ]]; then
        return 0
    fi

    old_pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [[ -z "${old_pid}" ]] || ! kill -0 "${old_pid}" 2>/dev/null; then
        rm -f "${pid_file}"
        return 0
    fi

    if process_uses_config "${old_pid}" "${expected_config}"; then
        log "Stopping legacy PID file instance (PID ${old_pid})"
        kill "${old_pid}" 2>/dev/null || true
        wait_for_exit "${old_pid}" 10
        if kill -0 "${old_pid}" 2>/dev/null; then
            log "Force-killing unresponsive process ${old_pid}"
            kill -9 "${old_pid}" 2>/dev/null || true
        fi
        rm -f "${pid_file}"
    else
        log "Leaving legacy PID file for another config (PID ${old_pid})"
    fi
}

# Return the PIDs of bot processes started with this exact config file. Each
# candidate is checked against the resolved absolute path of its own --conf,
# so two checkouts that both use bot.ini do not match each other.
straggler_pids() {
    local config_file="$1"
    local resolved pid

    resolved="$(realpath -m -- "${config_file}" 2>/dev/null || realpath -- "${config_file}" 2>/dev/null || printf '%s' "${config_file}")"
    while IFS= read -r pid; do
        [[ -n "${pid}" ]] || continue
        if process_uses_config "${pid}" "${resolved}"; then
            printf '%s\n' "${pid}"
        fi
    done < <(pgrep -f -- 'src\.main.*--conf' 2>/dev/null || true)
}
