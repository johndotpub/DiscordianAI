import configparser
import argparse
import os
import logging
import sys
from logging.handlers import RotatingFileHandler

# Define the function to parse command-line arguments
def parse_arguments() -> argparse.Namespace:
    try:
        parser = argparse.ArgumentParser(description='GPT-based Discord bot.')
        parser.add_argument('--conf', help='Configuration file path')
        args = parser.parse_args()
        return args
    except Exception as e:
        logger.error(f"Error parsing arguments: {e}")
        raise


# Define the function to load the configuration
def load_configuration(config_file: str) -> configparser.ConfigParser:
    try:
        config = configparser.ConfigParser()

        # Check if the configuration file exists
        if os.path.exists(config_file):
            config.read(config_file)
        else:
            # Fall back to environment variables
            config.read_dict(
                {section: dict(os.environ) for section in config.sections()}
            )

        return config
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        raise

# Executes the argparse code only when the file is run directly
if __name__ == "__main__":  # noqa: C901 (ignore complexity in main function)
    # Parse command-line arguments
    args = parse_arguments()

    # Load configuration
    config = load_configuration(args.conf)

    # Retrieve configuration details from the configuration file
    DISCORD_TOKEN = config.get('Discord', 'DISCORD_TOKEN')
    ALLOWED_CHANNELS = config.get(
        'Discord', 'ALLOWED_CHANNELS', fallback=''
        ).split(',')
    BOT_PRESENCE = config.get('Discord', 'BOT_PRESENCE', fallback='online')

    # ACTIVITY_TYPE playing, streaming, listening, watching, custom, competing
    ACTIVITY_TYPE = config.get(
        'Discord', 'ACTIVITY_TYPE', fallback='listening'
        )
    ACTIVITY_STATUS = config.get(
        'Discord', 'ACTIVITY_STATUS', fallback='Humans'
        )

    OPENAI_API_KEY = config.get('OpenAI', 'OPENAI_API_KEY')
    OPENAI_TIMEOUT = config.getint('OpenAI', 'OPENAI_TIMEOUT', fallback='30')
    GPT_MODEL = config.get(
        'OpenAI', 'GPT_MODEL', fallback='gpt-3.5-turbo-1106'
    )
    GPT_TOKENS = config.getint('OpenAI', 'GPT_TOKENS', fallback=4096)
    SYSTEM_MESSAGE = config.get(
        'OpenAI', 'SYSTEM_MESSAGE', fallback='You are a helpful assistant.'
    )

    RATE_LIMIT = config.getint('Limits', 'RATE_LIMIT', fallback=10)
    RATE_LIMIT_PER = config.getint('Limits', 'RATE_LIMIT_PER', fallback=60)

    LOG_FILE = config.get('Logging', 'LOG_FILE', fallback='bot.log')
    LOG_LEVEL = config.get('Logging', 'LOG_LEVEL', fallback='INFO')

    # Set up logging
    logger = logging.getLogger('discord')
    logger.setLevel(getattr(logging, LOG_LEVEL.upper()))

    # File handler
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Set a global exception handler
    def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_unhandled_exception