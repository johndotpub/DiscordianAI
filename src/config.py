import argparse
import configparser
import os
from typing import Any, Dict


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.
    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="GPT-based Discord bot.")
    parser.add_argument("--conf", help="Configuration file path")
    parser.add_argument("--folder", help="Base folder for config and logs")
    return parser.parse_args()


def load_config(config_file: str = None, base_folder: str = None) -> Dict[str, Any]:
    """
    Load configuration from a file (if provided), then environment variables,
    with a clear hierarchy.
    Args:
        config_file (str, optional): Path to the configuration file. Defaults to None.
    Returns:
        dict: Configuration dictionary with all settings.
    """
    config = configparser.ConfigParser()
    config_data = {}

    # If base_folder is provided, resolve config_file and log file paths
    if base_folder:
        if config_file and not os.path.isabs(config_file):
            config_file = os.path.join(base_folder, config_file)

    # 1. Load from file if provided and exists
    if config_file and os.path.exists(config_file):
        config.read(config_file)
        # Discord section
        config_data["DISCORD_TOKEN"] = config.get("Discord", "DISCORD_TOKEN", fallback=None)
        config_data["ALLOWED_CHANNELS"] = config.get(
            "Discord", "ALLOWED_CHANNELS", fallback=""
        ).split(",")
        config_data["BOT_PRESENCE"] = config.get("Discord", "BOT_PRESENCE", fallback="online")
        config_data["ACTIVITY_TYPE"] = config.get("Discord", "ACTIVITY_TYPE", fallback="listening")
        config_data["ACTIVITY_STATUS"] = config.get(
            "Discord", "ACTIVITY_STATUS", fallback="Humans"
        )
        # Default section
        config_data["API_KEY"] = config.get("Default", "API_KEY", fallback=None)
        config_data["API_URL"] = config.get(
            "Default", "API_URL", fallback="https://api.openai.com/v1/"
        )
        config_data["GPT_MODEL"] = config.get("Default", "GPT_MODEL", fallback="gpt-4o-mini")
        config_data["INPUT_TOKENS"] = config.getint("Default", "INPUT_TOKENS", fallback=120000)
        config_data["OUTPUT_TOKENS"] = config.getint("Default", "OUTPUT_TOKENS", fallback=8000)
        config_data["CONTEXT_WINDOW"] = config.getint("Default", "CONTEXT_WINDOW", fallback=128000)
        config_data["SYSTEM_MESSAGE"] = config.get(
            "Default", "SYSTEM_MESSAGE", fallback="You are a helpful assistant."
        )
        # Limits section
        config_data["RATE_LIMIT"] = config.getint("Limits", "RATE_LIMIT", fallback=10)
        config_data["RATE_LIMIT_PER"] = config.getint("Limits", "RATE_LIMIT_PER", fallback=60)
        # Logging section
        config_data["LOG_FILE"] = config.get("Logging", "LOG_FILE", fallback="bot.log")
        if base_folder and not os.path.isabs(config_data["LOG_FILE"]):
            config_data["LOG_FILE"] = os.path.join(base_folder, config_data["LOG_FILE"])
        config_data["LOG_LEVEL"] = config.get("Logging", "LOG_LEVEL", fallback="INFO")

    # 2. Override with environment variables if set
    env_overrides = {
        "DISCORD_TOKEN": os.environ.get("DISCORD_TOKEN"),
        "ALLOWED_CHANNELS": os.environ.get("ALLOWED_CHANNELS"),
        "BOT_PRESENCE": os.environ.get("BOT_PRESENCE"),
        "ACTIVITY_TYPE": os.environ.get("ACTIVITY_TYPE"),
        "ACTIVITY_STATUS": os.environ.get("ACTIVITY_STATUS"),
        "API_KEY": os.environ.get("API_KEY"),
        "API_URL": os.environ.get("API_URL"),
        "GPT_MODEL": os.environ.get("GPT_MODEL"),
        "INPUT_TOKENS": os.environ.get("INPUT_TOKENS"),
        "OUTPUT_TOKENS": os.environ.get("OUTPUT_TOKENS"),
        "CONTEXT_WINDOW": os.environ.get("CONTEXT_WINDOW"),
        "SYSTEM_MESSAGE": os.environ.get("SYSTEM_MESSAGE"),
        "RATE_LIMIT": os.environ.get("RATE_LIMIT"),
        "RATE_LIMIT_PER": os.environ.get("RATE_LIMIT_PER"),
        "LOG_FILE": os.environ.get("LOG_FILE"),
        "LOG_LEVEL": os.environ.get("LOG_LEVEL"),
    }
    for key, value in env_overrides.items():
        if value is not None:
            if key == "ALLOWED_CHANNELS":
                config_data[key] = value.split(",")
            elif key in {
                "INPUT_TOKENS",
                "OUTPUT_TOKENS",
                "CONTEXT_WINDOW",
                "RATE_LIMIT",
                "RATE_LIMIT_PER",
            }:
                try:
                    config_data[key] = int(value)
                except ValueError:
                    pass  # Ignore invalid int conversion
            else:
                config_data[key] = value

    # 3. Set defaults if still missing
    defaults = {
        "DISCORD_TOKEN": None,
        "ALLOWED_CHANNELS": [],
        "BOT_PRESENCE": "online",
        "ACTIVITY_TYPE": "listening",
        "ACTIVITY_STATUS": "Humans",
        "API_KEY": None,
        "API_URL": "https://api.openai.com/v1/",
        "GPT_MODEL": "gpt-4o-mini",
        "INPUT_TOKENS": 120000,
        "OUTPUT_TOKENS": 8000,
        "CONTEXT_WINDOW": 128000,
        "SYSTEM_MESSAGE": "You are a helpful assistant.",
        "RATE_LIMIT": 10,
        "RATE_LIMIT_PER": 60,
        "LOG_FILE": "bot.log",
        "LOG_LEVEL": "INFO",
    }
    for key, value in defaults.items():
        if key not in config_data or config_data[key] is None:
            config_data[key] = value

    return config_data
