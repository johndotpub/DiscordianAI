#!/bin/bash

# Define PATH if running from crontab. Adjust as necessary.
# PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Script for launching a DiscordianAI bot with customizable configurations.
# Suitable for both manual execution and running via crontab.

# Enable strict error checking: Exit on any error and recognize failures in pipelines.
set -e
set -o pipefail

# Logging function with timestamp for better tracking
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Find and log the path to the python3 executable.
python3="$(which python3)"
log "Using python3 binary: $python3"

# Default configuration and output settings
config_file="bot.ini"  # Default configuration file.
output=""              # No output redirection initially.
base_folder=""         # Use current directory by default.

# Process command line arguments to adjust script settings
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -d|--daemon)
            # Daemon mode: No output to terminal
            output="/dev/null"
            log "Running in daemon mode. Output redirected to $output"
            ;;
        -b|--background)
            # Background mode: Output to nohup.out
            output="nohup.out"
            log "Running in background mode. Output redirected to $output"
            ;;
        -c|--config)
            # Custom configuration file: Ensure argument is provided
            if [[ -n "$2" && ! "$2" =~ ^- ]]; then
                config_file="$2"
                shift  # Skip next argument
                log "Using custom config file: $config_file"
            else
                log "Error: Configuration file argument required."
                exit 1
            fi
            ;;
        -f|--folder)
            # Base folder: Ensure argument is a valid path
            if [[ -n "$2" && ! "$2" =~ ^- ]]; then
                base_folder="$(realpath "$2")"
                shift  # Skip next argument
                log "Using base folder: $base_folder"
            else
                log "Error: Folder path argument required."
                exit 1
            fi
            ;;
        *)
            # Ignore unrecognized options
            ;;
    esac
    shift  # Move to next argument
done

# Construct the command with the base folder and config file.
# If base_folder is set, prepend it to both bot.py and config file paths.
if [[ -n $base_folder ]]; then
    config_file="$base_folder/$config_file"
    command="$python3 $base_folder/bot.py --conf $config_file"
else
    command="$python3 bot.py --conf $config_file"
fi
log "Command to execute: $command"

# Enhanced error handling
trap 'log "An error occurred. Exiting..."; exit 1' ERR

# Terminate existing instances of the bot
log "Killing existing instances of the bot..."
pkill -f "bot.py --conf" || true

# Decide execution mode based on output setting
if [[ -z $output ]]; then
    # Normal execution
    eval "$command"
else
    # Background or daemon execution
    log "Running command in background: $command > $output 2>&1 &"
    if ! ($command > "$output" 2>&1 &); then
        log "Error: Failed to execute command."
        exit 1
    fi
fi

# Log successful execution completion
log "Script execution completed successfully."
