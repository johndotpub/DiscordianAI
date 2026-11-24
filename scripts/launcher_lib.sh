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

# PID file for one config, derived from its file stem and the resolved
# absolute config path. The hash separates two configs that share a basename
# but live in different directories.
instance_pid_file() {
    local project_dir="$1"
    local config_file="$2"
    local stem resolved digest

    stem="$(basename -- "${config_file}")"
    stem="${stem%.ini}"
    resolved="$(resolve_config_path "${project_dir}" "${config_file}")"
    digest="$(printf '%s' "${resolved}" | cksum)"
    digest="${digest%% *}"
    printf '%s/.bot-%s-%s.pid\n' "${project_dir}" "${stem}" "${digest:0:8}"
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

# The argument that follows --conf, preserving spaces. /proc keeps arguments
# NUL-separated, so a path such as "/srv/my bot/bot.ini" stays one argument.
process_conf_argument() {
    local pid="$1"
    local previous="" argument cmdline

    if [[ -r "/proc/${pid}/cmdline" ]]; then
        while IFS= read -r argument; do
            if [[ "${previous}" == "--conf" ]]; then
                printf '%s\n' "${argument}"
                return 0
            fi
            previous="${argument}"
        done < <(tr '\0' '\n' < "/proc/${pid}/cmdline" 2>/dev/null || true)
    fi

    cmdline="$(process_command_line "${pid}")"
    [[ -n "${cmdline}" ]] || return 1
    printf '%s\n' "${cmdline}" | sed -n 's/.*--conf[[:space:]][[:space:]]*\([^[:space:]]*\).*/\1/p' | head -n 1
}

# True when the process was started with this exact config file. A relative
# --conf value is resolved against the process's own working directory.
process_uses_config() {
    local pid="$1"
    local expected_config="$2"
    local conf_arg cwd resolved

    conf_arg="$(process_conf_argument "${pid}")"
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

# Seconds to wait for a signalled process before forcing it. Tests and unusual
# supervisors can shorten it; the default keeps the documented 10 seconds.
launcher_stop_timeout() {
    local timeout="${DISCORDIANAI_STOP_TIMEOUT:-10}"

    if [[ "${timeout}" =~ ^[0-9]+$ ]]; then
        printf '%s\n' "${timeout}"
    else
        printf '10\n'
    fi
}

# True while the process is alive. A zombie has exited for our purposes even
# though kill -0 still succeeds until its parent reaps it.
process_is_running() {
    local pid="$1"
    local state=""

    kill -0 "${pid}" 2>/dev/null || return 1
    if [[ -r "/proc/${pid}/stat" ]]; then
        state="$(sed -n 's/^[^)]*) \([A-Za-z]\).*/\1/p' "/proc/${pid}/stat" 2>/dev/null || true)"
        [[ "${state}" != "Z" ]] || return 1
    fi
    return 0
}

# Wait up to timeout seconds for the process to exit. The caller checks
# liveness afterwards; this returns successfully even when the timeout expires.
wait_for_exit() {
    local pid="$1"
    local timeout="${2:-10}"
    local checks=$((timeout * 10))
    local waited=0

    while process_is_running "${pid}" && [[ "${waited}" -lt "${checks}" ]]; do
        sleep 0.1
        waited=$((waited + 1))
    done
}

# Stop the instance recorded in a PID file, then always remove the file. The
# PID is signalled only when its command line runs this same config; a stale
# file left after a reboot may name an unrelated process.
stop_pid_file_instance() {
    local pid_file="$1"
    local expected_config="${2:-}"

    if [[ ! -f "${pid_file}" ]]; then
        return 0
    fi

    local old_pid
    old_pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [[ -n "${old_pid}" ]] && process_is_running "${old_pid}"; then
        if [[ -n "${expected_config}" ]] && ! process_uses_config "${old_pid}" "${expected_config}"; then
            log "PID file records another process (PID ${old_pid}); not signalling it"
        else
            log "Stopping previous instance (PID ${old_pid})"
            kill "${old_pid}" 2>/dev/null || true
            wait_for_exit "${old_pid}" "$(launcher_stop_timeout)"
            if process_is_running "${old_pid}"; then
                log "Force-killing unresponsive process ${old_pid}"
                kill -9 "${old_pid}" 2>/dev/null || true
            fi
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
    if [[ -z "${old_pid}" ]] || ! process_is_running "${old_pid}"; then
        rm -f "${pid_file}"
        return 0
    fi

    if process_uses_config "${old_pid}" "${expected_config}"; then
        log "Stopping legacy PID file instance (PID ${old_pid})"
        kill "${old_pid}" 2>/dev/null || true
        wait_for_exit "${old_pid}" "$(launcher_stop_timeout)"
        if process_is_running "${old_pid}"; then
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
