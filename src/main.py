from .config import parse_arguments
from .config import load_configuration
from .bot import bot

def main():
    # Parse command-line arguments
    args = parse_arguments()

    # Load configuration
    config = load_configuration(args.conf)

    # Retrieve DISCORD_TOKEN from configuration
    DISCORD_TOKEN = config.get('Discord', 'DISCORD_TOKEN')

    # Run the bot
    bot.run(DISCORD_TOKEN)

if __name__ == "__main__":
    main()
