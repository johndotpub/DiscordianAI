# Standard library imports
import argparse
import asyncio
import configparser
import logging
import os
import re
import sys
import time
from logging.handlers import RotatingFileHandler

# Third-party imports
import discord
from openai import OpenAI
from websockets.exceptions import ConnectionClosed

class RateLimiter:
    def __init__(self):
        self.last_command_timestamps = {}
        self.last_command_count = {}

    def check_rate_limit(self, user_id: int, rate_limit: int, rate_limit_per: int, logger: logging.Logger) -> bool:
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

def set_activity_status(
    activity_type: str,
    activity_status: str
) -> discord.Activity:
    """
    Return discord.Activity object with specified activity type and status
    """
    try:
        activity_types = {
            'playing': discord.ActivityType.playing,
            'streaming': discord.ActivityType.streaming,
            'listening': discord.ActivityType.listening,
            'watching': discord.ActivityType.watching,
            'custom': discord.ActivityType.custom,
            'competing': discord.ActivityType.competing
        }
        return discord.Activity(
            type=activity_types.get(
                activity_type, discord.ActivityType.listening
            ),
            name=activity_status
        )
    except Exception as e:
        logger.error(f"Error setting activity status: {e}")
        raise

# Define the function to get the conversation summary
def get_conversation_summary(conversation: list[dict]) -> list[dict]:
    """
    Conversation summary from combining user messages and assistant responses
    """
    try:
        summary = []
        user_messages = [
            message for message in conversation if message["role"] == "user"
        ]
        assistant_responses = [
            message for message in conversation if message["role"] == "assistant"
        ]

        # Combine user messages and assistant responses into a summary
        for user_message, assistant_response in zip(
            user_messages, assistant_responses
        ):
            summary.append(user_message)
            summary.append(assistant_response)

        return summary
    except Exception as e:
        logger.error(f"Error getting conversation summary: {e}")
        raise

async def check_rate_limit(
    user: discord.User,
    rate_limiter: RateLimiter,
    rate_limit: int,
    rate_limit_per: int,
    logger: logging.Logger = None
) -> bool:
    """
    Check if a user has exceeded the rate limit for sending messages.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    try:
        return rate_limiter.check_rate_limit(user.id, rate_limit, rate_limit_per, logger)
    except Exception as e:
        logger.error(f"Error checking rate limit: {e}")
        raise

async def process_input_message(
    input_message: str,
    user: discord.User,
    conversation_summary: list[dict]
) -> str:
    """
    Process an input message using the GPT model.
    """
    try:
        logger.info("Sending prompt to the API.")

        INPUT_PROMPT = {"role": "user", "content": input_message}

        conversation = conversation_history.get(user.id, [])
        conversation.append({"role": "user", "content": input_message})

        conversation_tokens = sum(
            len(message["content"].split()) for message in conversation
        )

        if conversation_tokens >= GPT_TOKENS * 0.8:
            conversation_summary = get_conversation_summary(conversation)
            conversation_tokens_summary = sum(
                len(message["content"].split())
                for message in conversation_summary
            )
            max_tokens = GPT_TOKENS - conversation_tokens_summary
        else:
            max_tokens = GPT_TOKENS - conversation_tokens

        # Log the current conversation history
        # logger.info(f"Current conversation history: {conversation}")

        def call_openai_api():
            return client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_MESSAGE},
                    *conversation_summary,
                    {"role": "user", "content": input_message}
                ],
                max_tokens=max_tokens,
                temperature=0.7
            )

        response = await asyncio.to_thread(call_openai_api)

        try:
            # Extracting the response content from the new API response format
            if response.choices:
                response_content = response.choices[0].message.content.strip()
            else:
                response_content = None
        except AttributeError:
            logger.error(
                "Failed to get response from the API: "
                "Invalid response format."
            )
            return "Sorry, an error occurred while processing the message."

        if response_content:
            logger.info("Received response from the API.")
            # Debugging: Log the raw response
            # logger.info(f"Raw API response: {response}")
            logger.info(f"Sent the response: {response_content}")

            conversation.append(
                {"role": "assistant", "content": response_content}
            )
            conversation_history[user.id] = conversation

            return response_content
        else:
            logger.error("API error: No response text.")
            return "Sorry, I didn't get that. Can you rephrase or ask again?"

    except ConnectionClosed as error:
        logger.error(f"WebSocket connection closed: {error}")
        logger.info("Reconnecting in 5 seconds...")
        await asyncio.sleep(5)
        await bot.login(DISCORD_TOKEN)
        await bot.connect(reconnect=True)
    except Exception as error:
        logger.error("An error processing message: %s", error)
        return "An error occurred while processing the message."

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

    # Set your Defaults
    API_KEY = config.get('Default', 'API_KEY')
    API_URL = config.get(
        'Default', 'API_URL', fallback='https://api.openai.com/v1/'
    )
    GPT_MODEL = config.get(
        'Default', 'GPT_MODEL', fallback='gpt-3.5-turbo-1106'
    )
    GPT_TOKENS = config.getint('Default', 'GPT_TOKENS', fallback=4096)
    SYSTEM_MESSAGE = config.get(
        'Default', 'SYSTEM_MESSAGE', fallback='You are a helpful assistant.'
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

    # Set the intents for the bot
    intents = discord.Intents.default()
    intents.typing = False
    intents.presences = False

    # Create a dictionary to store conversation history for each user
    conversation_history = {}

    # Setup the Bot's Personality
    SYSTEM_PROMPT = {"role": "system", "content": SYSTEM_MESSAGE}
    
    # Create the bot instance
    bot = discord.Client(intents=intents)

    # Create the API client instance
    client = OpenAI(
        api_key=API_KEY,
        api_base=API_URL
    )

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
        await bot.change_presence(
            activity=activity,
            status=discord.Status(BOT_PRESENCE)
        )

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
        """
        logger.info(f'Shard {shard_id} is ready')

    @bot.event
    async def on_message(message):
        """
        Event handler for when a message is received.
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

    async def process_dm_message(message):
        """
        Process a direct message.
        """
        logger.info(
            f'Received DM from {message.author}: {message.content}'
        )

        if not await check_rate_limit(message.author, rate_limiter, RATE_LIMIT, RATE_LIMIT_PER):
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

        if not await check_rate_limit(message.author, rate_limiter, RATE_LIMIT, RATE_LIMIT_PER):
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

    # Run the bot
    bot.run(DISCORD_TOKEN)