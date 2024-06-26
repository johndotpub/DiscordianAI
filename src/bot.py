# Standard library imports
import asyncio
import logging
import re
import time

# Third-party imports
from openai import OpenAI


# Local application imports
from .conversations import get_conversation_summary
from .discord_bot import set_activity_status
from .rate_limits import check_rate_limit
from .config import GPT_MODEL, GPT_TOKENS, OPENAI_API_KEY, SYSTEM_MESSAGE


class RateLimiter:
    """Class to handle rate limiting for users."""

    def __init__(self):
        """Initialize the RateLimiter with empty dictionaries."""
        self.last_command_timestamps = {}
        self.last_command_count = {}

    def check_rate_limit(
        self,
        user_id: int,
        rate_limit: int,
        rate_limit_per: int,
        logger: logging.Logger
    ) -> bool:
        """
        Check if a user has exceeded the rate limit.

        Args:
            user_id (int): The ID of the user.
            rate_limit (int): The maximum number of allowed commands.
            rate_limit_per (int): The time period for the rate limit.
            logger (logging.Logger): The logger instance.

        Returns:
            bool: True if the user is within the rate limit, False otherwise.
        """
        current_time = time.time()
        last_command_timestamp = self.last_command_timestamps.get(user_id, 0)
        last_command_count_user = self.last_command_count.get(user_id, 0)

        if current_time - last_command_timestamp > rate_limit_per:
            self.last_command_timestamps[user_id] = current_time
            self.last_command_count[user_id] = 1
            logger.info(f"Rate limit passed for user: {user_id}")
            return True

        if last_command_count_user < rate_limit:
            self.last_command_count[user_id] += 1
            logger.info(f"Rate limit passed for user: {user_id}")
            return True

        logger.info(f"Rate limit exceeded for user: {user_id}")
        return False


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description='GPT-based Discord bot.')
    parser.add_argument('--conf', help='Configuration file path')
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
        config.read_dict({section: dict(os.environ) for section in config.sections()})

    return config


def set_activity_status(activity_type: str, activity_status: str) -> discord.Activity:
    """
    Return discord.Activity object with specified activity type and status.

    Args:
        activity_type (str): The type of activity.
        activity_status (str): The status of the activity.

    Returns:
        discord.Activity: The activity object.
    """
    activity_types = {
        'playing': discord.ActivityType.playing,
        'streaming': discord.ActivityType.streaming,
        'listening': discord.ActivityType.listening,
        'watching': discord.ActivityType.watching,
        'custom': discord.ActivityType.custom,
        'competing': discord.ActivityType.competing
    }
    return discord.Activity(
        type=activity_types.get(activity_type, discord.ActivityType.listening),
        name=activity_status
    )


def get_conversation_summary(conversation: list[dict]) -> list[dict]:
    """
    Get a summary of the conversation.

    Args:
        conversation (list[dict]): The conversation history.

    Returns:
        list[dict]: The summarized conversation.
    """
    summary = []
    user_messages = [msg for msg in conversation if msg["role"] == "user"]
    assistant_responses = [msg for msg in conversation if msg["role"] == "assistant"]

    for user_msg, assistant_resp in zip(user_messages, assistant_responses):
        summary.append(user_msg)
        summary.append(assistant_resp)

    return summary


async def check_rate_limit(
    user: discord.User,
    rate_limiter: RateLimiter,
    rate_limit: int,
    rate_limit_per: int,
    logger: logging.Logger = None
) -> bool:
    """
    Check if a user has exceeded the rate limit for sending messages.

    Args:
        user (discord.User): The user to check.
        rate_limiter (RateLimiter): The rate limiter instance.
        rate_limit (int): The maximum number of allowed commands.
        rate_limit_per (int): The time period for the rate limit.
        logger (logging.Logger, optional): The logger instance. Defaults to None.

    Returns:
        bool: True if the user is within the rate limit, False otherwise.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    return rate_limiter.check_rate_limit(user.id, rate_limit, rate_limit_per, logger)


async def process_input_message(
    input_message: str,
    user: discord.User,
    conversation_summary: list[dict]
) -> str:
    """
    Process an input message using the GPT model.

    Args:
        input_message (str): The input message from the user.
        user (discord.User): The user who sent the message.
        conversation_summary (list[dict]): The conversation summary.

    Returns:
        str: The response from the GPT model.
    """
    logger.info("Sending prompt to the API.")

    conversation = CONVERSATION_HISTORY.get(user.id, [])
    conversation.append({"role": "user", "content": input_message})

    def call_openai_api():
        logger.debug(f"GPT_MODEL: {GPT_MODEL}")
        logger.debug(f"SYSTEM_MESSAGE: {SYSTEM_MESSAGE}")
        logger.debug(f"conversation_summary: {conversation_summary}")
        logger.debug(f"input_message: {input_message}")

        return client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_MESSAGE},
                *conversation_summary,
                {"role": "user", "content": input_message}
            ],
            max_tokens=OUTPUT_TOKENS,
            temperature=0.7
        )

    response = await asyncio.to_thread(call_openai_api)
    logger.debug(f"Full API response: {response}")

    try:
        if response.choices:
            response_content = response.choices[0].message.content.strip()
        else:
            response_content = None
    except AttributeError as e:
        logger.error(f"Failed to get response from the API: {e}")
        return "Sorry, an error occurred while processing the message."

    if response_content:
        logger.info("Received response from the API.")
        logger.info(f"Sent the response: {response_content}")

        conversation.append({"role": "assistant", "content": response_content})
        CONVERSATION_HISTORY[user.id] = conversation

        return response_content
    else:
        logger.error("API error: No response text.")
        return "Sorry, I didn't get that. Can you rephrase or ask again?"


async def process_dm_message(message: discord.Message):
    """
    Process a direct message.

    Args:
        message (discord.Message): The direct message received.
    """
    logger.info(f'Received DM from {message.author}: {message.content}')

    if not await check_rate_limit(message.author, rate_limiter, RATE_LIMIT, RATE_LIMIT_PER):
        await message.channel.send(
            f"{message.author.mention} Exceeded the Rate Limit! Please slow down!"
        )
        logger.warning(f"Rate Limit Exceeded by DM from {message.author}")
        return

    conversation_summary = get_conversation_summary(
        CONVERSATION_HISTORY.get(message.author.id, [])
    )
    response = await process_input_message(
        message.content, message.author, conversation_summary
    )
    await send_split_message(message.channel, response)


async def process_channel_message(message: discord.Message):
    """
    Process a message in a channel.

    Args:
        message (discord.Message): The message received in a channel.
    """
    logger.info(
        'Received message in {} from {}: {}'.format(
            str(message.channel),
            str(message.author),
            re.sub(r'<@\d+>', '', message.content)
        )
    )

    if not await check_rate_limit(message.author, rate_limiter, RATE_LIMIT, RATE_LIMIT_PER):
        await message.channel.send(
            f"{message.author.mention} Exceeded the Rate Limit! Please slow down!"
        )
        logger.warning(f"Rate Limit Exceeded in {message.channel} by {message.author}")
        return

    conversation_summary = get_conversation_summary(
        CONVERSATION_HISTORY.get(message.author.id, [])
    )
    response = await process_input_message(
        message.content, message.author, conversation_summary
    )
    await send_split_message(message.channel, response)


async def send_split_message(channel: discord.abc.Messageable, message: str):
    """
    Send a message to a channel, splitting it if necessary.

    Args:
        channel (discord.abc.Messageable): The channel to send the message to.
        message (str): The message to send.
    """
    if len(message) <= 2000:
        await channel.send(message)
    else:
        # Find the middle index
        middle_index = len(message) // 2

        # Find the nearest newline before the middle index
        split_index = message.rfind('\n', 0, middle_index)
        if split_index == -1:
            split_index = middle_index

        # Adjust split index to avoid splitting code blocks
        before_split = message[:split_index]
        after_split = message[split_index:]

        # Check if the split occurs within a code block
        if before_split.count('```') % 2 != 0:
            # Find the next newline after the middle index
            split_index = message.find('\n', middle_index)
            if split_index == -1:
                split_index = middle_index

            before_split = message[:split_index]
            after_split = message[split_index:]

        # Ensure no leading/trailing whitespace
        message_part1 = before_split.strip()
        message_part2 = after_split.strip()

        await channel.send(message_part1)
        await send_split_message(channel, message_part2)


if __name__ == "__main__":  # noqa: C901 (ignore complexity in main function)
    # Parse command-line arguments
    args = parse_arguments()

    # Load configuration
    config = load_configuration(args.conf)

    # Retrieve configuration details from the configuration file
    DISCORD_TOKEN = config.get('Discord', 'DISCORD_TOKEN')
    ALLOWED_CHANNELS = config.get('Discord', 'ALLOWED_CHANNELS', fallback='').split(',')
    BOT_PRESENCE = config.get('Discord', 'BOT_PRESENCE', fallback='online')
    ACTIVITY_TYPE = config.get('Discord', 'ACTIVITY_TYPE', fallback='listening')
    ACTIVITY_STATUS = config.get('Discord', 'ACTIVITY_STATUS', fallback='Humans')
    API_KEY = config.get('Default', 'API_KEY')
    API_URL = config.get('Default', 'API_URL', fallback='https://api.openai.com/v1/')
    GPT_MODEL = config.get('Default', 'GPT_MODEL', fallback='gpt-4o-mini')
    INPUT_TOKENS = config.getint('Default', 'INPUT_TOKENS', fallback=120000)
    OUTPUT_TOKENS = config.getint('Default', 'OUTPUT_TOKENS', fallback=8000)
    CONTEXT_WINDOW = config.getint('Default', 'CONTEXT_WINDOW', fallback=128000)
    SYSTEM_MESSAGE = config.get(
        'Default', 'SYSTEM_MESSAGE', fallback='You are a helpful assistant.')
    RATE_LIMIT = config.getint('Limits', 'RATE_LIMIT', fallback=10)
    RATE_LIMIT_PER = config.getint('Limits', 'RATE_LIMIT_PER', fallback=60)
    LOG_FILE = config.get('Logging', 'LOG_FILE', fallback='bot.log')
    LOG_LEVEL = config.get('Logging', 'LOG_LEVEL', fallback='INFO')

    # Set up logging
    logger = logging.getLogger('discord')
    logger.setLevel(getattr(logging, LOG_LEVEL.upper()))

    # File handler
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5)
    file_handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Set a global exception handler
    def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_unhandled_exception

    # Set the intents for the bot
    intents = discord.Intents.default()
    intents.typing = False
    intents.presences = False

    # Create a dictionary to store conversation history for each user
    CONVERSATION_HISTORY = {}

    # Create the bot instance
    bot = discord.Client(intents=intents)

    # Set the API key and base URL
    client = OpenAI(api_key=API_KEY, base_url=API_URL)

    # Initialize rate limiter
    rate_limiter = RateLimiter()

    @bot.event
    async def on_ready():
        """
        Event handler for when the bot is ready to receive messages.
        """
        logger.info(f'We have logged in as {bot.user}')
        logger.info(f'Configured bot presence: {BOT_PRESENCE}')
        logger.info(f'Configured activity type: {ACTIVITY_TYPE}')
        logger.info(f'Configured activity status: {ACTIVITY_STATUS}')
        activity = set_activity_status(ACTIVITY_TYPE, ACTIVITY_STATUS)
        await bot.change_presence(activity=activity, status=discord.Status(BOT_PRESENCE))

    @bot.event
    async def on_disconnect():
        """
        Event handler for when the bot disconnects from the Discord server.
        """
        logger.info('Bot has disconnected')

    @bot.event
    async def on_resumed():
        """
        Event handler for when the bot resumes its session.
        """
        logger.info('Bot has resumed session')

    @bot.event
    async def on_shard_ready(shard_id):
        """
        Event handler for when a shard is ready.

        Args:
            shard_id: The ID of the shard.
        """
        logger.info(f'Shard {shard_id} is ready')

    @bot.event
    async def on_message(message: discord.Message):
        """
        Event handler for when a message is received.

        Args:
            message (discord.Message): The message received.
        """
        try:
            if message.author == bot.user:
                return

            if isinstance(message.channel, discord.DMChannel):
                await process_dm_message(message)
            elif (
                isinstance(message.channel, discord.TextChannel)
                and message.channel.name in ALLOWED_CHANNELS
                and bot.user in message.mentions
            ):
                await process_channel_message(message)
        except Exception as e:
            logger.error(f"An error occurred in on_message: {e}")

    # Run the bot
    bot.run(DISCORD_TOKEN)


    async def process_dm_message(message):
        """
        Process a direct message.
        """
        logger.info(
            f'Received DM from {message.author}: {message.content}'
        )

        if not await check_rate_limit(message.author):
            await message.channel.send(
                f"{message.author.mention} Exceeded the Rate Limit! Please slow down!"
            )
            logger.warning(f"Rate Limit Exceed by DM from {message.author}")
            return

        conversation_summary = get_conversation_summary(
            conversation_history.get(message.author.id, [])
        )
        response = await process_input_message(
            message.content, message.author, conversation_summary
        )
        await send_split_message(message.channel, response)

    async def process_channel_message(message):
        """
        Process a message in a channel.
        """
        logger.info(
            'Received message in {} from {}: {}'.format(
                str(message.channel),
                str(message.author),
                re.sub(r'<@\d+>', '', message.content)
            )
        )

        if not await check_rate_limit(message.author):
            await message.channel.send(
                f"{message.author.mention} Exceeded the Rate Limit! Please slow down!"
            )
            logger.warning(f"Rate Limit Exceeded in {message.channel} by {message.author}")
            return

        conversation_summary = get_conversation_summary(
            conversation_history.get(message.author.id, [])
        )
        response = await process_input_message(
            message.content, message.author, conversation_summary
        )
        await send_split_message(message.channel, response)

    async def send_split_message(channel, message):
        """
        Send a message to a channel. If the message is longer than 2000 characters,
        it is split into multiple messages at the nearest newline character around
        the middle of the message.
        """
        if len(message) <= 2000:
            await channel.send(message)
        else:
            # Find the nearest newline character around the middle of the message
            middle_index = len(message) // 2
            split_index = message.rfind('\n', 0, middle_index)
            if split_index == -1:  # No newline character found
                split_index = middle_index  # Split at the middle of the message
            # Split the message into two parts
            message_part1 = message[:split_index]
            message_part2 = message[split_index:]
            # Send the two parts as separate messages
            await channel.send(message_part1)
            await channel.send(message_part2)
