from .config import load_configuration
from .discord_bot import run_bot


def main():
    config = load_configuration('path/to/config/file')
    run_bot(config)


if __name__ == "__main__":
    main()
