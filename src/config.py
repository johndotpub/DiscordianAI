import argparse
import configparser
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="GPT-based Discord bot.")
    parser.add_argument("--conf", help="Configuration file path")
    return parser.parse_args()


def load_configuration(config_file: str) -> configparser.ConfigParser:
    """
    Load the configuration from a file or environment variables.

    Args:
        config_file (str): Path to the configuration file.

    Returns:
        configparser.ConfigParser: Loaded configuration.
    """
    config = configparser.ConfigParser()

    if os.path.exists(config_file):
        config.read(config_file)
    else:
        default_sections = {
            'Default': dict(os.environ),
            'Discord': dict(os.environ),
            'Limits': dict(os.environ),
            'Logging': dict(os.environ),
        }
        config.read_dict(default_sections)

    return config


# Define config constants for import by other modules
GPT_MODEL = os.environ.get("GPT_MODEL", "gpt-4o-mini")
OUTPUT_TOKENS = int(os.environ.get("OUTPUT_TOKENS", 8000))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SYSTEM_MESSAGE = os.environ.get("SYSTEM_MESSAGE", "You are a helpful assistant.")
API_KEY = os.environ.get("API_KEY", "")
API_URL = os.environ.get("API_URL", "https://api.openai.com/v1/")
ALLOWED_CHANNELS = os.environ.get("ALLOWED_CHANNELS", "").split(",")
BOT_PRESENCE = os.environ.get("BOT_PRESENCE", "online")
ACTIVITY_TYPE = os.environ.get("ACTIVITY_TYPE", "listening")
ACTIVITY_STATUS = os.environ.get("ACTIVITY_STATUS", "Humans")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", 10))
RATE_LIMIT_PER = int(os.environ.get("RATE_LIMIT_PER", 60))


if __name__ == "__main__":  # noqa: C901 (ignore complexity in main function)
    # Parse command-line arguments
    args = parse_arguments()

    # Load configuration
    config = load_configuration(args.conf)

    # Retrieve configuration details from the configuration file
    # DISCORD_TOKEN = config.get("Discord", "DISCORD_TOKEN") # This line is now redundant
    # ALLOWED_CHANNELS = config.get("Discord", "ALLOWED_CHANNELS", fallback="").split(",") # This line is now redundant
    # BOT_PRESENCE = config.get("Discord", "BOT_PRESENCE", fallback="online") # This line is now redundant
    # ACTIVITY_TYPE = config.get("Discord", "ACTIVITY_TYPE", fallback="listening") # This line is now redundant
    # ACTIVITY_STATUS = config.get("Discord", "ACTIVITY_STATUS", fallback="Humans") # This line is now redundant
    # API_KEY = config.get("Default", "API_KEY") # This line is now redundant
    # API_URL = config.get("Default", "API_URL", fallback="https://api.openai.com/v1/") # This line is now redundant
    # GPT_MODEL = config.get("Default", "GPT_MODEL", fallback="gpt-4o-mini") # This line is now redundant
    # INPUT_TOKENS = config.getint("Default", "INPUT_TOKENS", fallback=120000) # This line is now redundant
    # OUTPUT_TOKENS = config.getint("Default", "OUTPUT_TOKENS", fallback=8000) # This line is now redundant
    # CONTEXT_WINDOW = config.getint("Default", "CONTEXT_WINDOW", fallback=128000) # This line is now redundant
    # SYSTEM_MESSAGE = config.get(
    #     "Default", "SYSTEM_MESSAGE", fallback="You are a helpful assistant."
    # ) # This line is now redundant
    # RATE_LIMIT = config.getint("Limits", "RATE_LIMIT", fallback=10) # This line is now redundant
    # RATE_LIMIT_PER = config.getint("Limits", "RATE_LIMIT_PER", fallback=60) # This line is now redundant
    LOG_FILE = config.get("Logging", "LOG_FILE", fallback="bot.log")
    LOG_LEVEL = config.get("Logging", "LOG_LEVEL", fallback="INFO")

    # Set up logging
    logger = logging.getLogger("discord")
    logger.setLevel(getattr(logging, LOG_LEVEL.upper()))

    # File handler
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Set a global exception handler
    def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.error(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = handle_unhandled_exception
