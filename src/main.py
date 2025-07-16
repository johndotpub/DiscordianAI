import logging
import sys

from .bot import run_bot
from .config import load_config, parse_arguments


def main():
    # Parse command-line arguments
    args = parse_arguments()

    # Set up global exception handler
    def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("discordianai").error(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = handle_unhandled_exception

    # Load configuration (file, env, defaults)
    config = load_config(args.conf, getattr(args, "folder", None))

    # Set up logging output to file
    logging.basicConfig(
        filename=config["LOG_FILE"],
        level=getattr(logging, config["LOG_LEVEL"].upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Start the bot with the loaded config
    run_bot(config)


if __name__ == "__main__":
    main()
