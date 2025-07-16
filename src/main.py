from .config import load_config, parse_arguments
from .bot import run_bot


def main():
    # Parse command-line arguments
    args = parse_arguments()

    # Load configuration (file, env, defaults)
    config = load_config(args.conf)

    # Start the bot with the loaded config
    run_bot(config)


if __name__ == "__main__":
    main()
