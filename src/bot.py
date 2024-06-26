# Standard library imports
import asyncio
import logging
import re
import time

# Third-party imports
from openai import OpenAI
from websockets.exceptions import ConnectionClosed

# Local application imports
from .conversations import get_conversation_summary
from .discord_bot import set_activity_status
from .rate_limits import check_rate_limit
from .config import GPT_MODEL, GPT_TOKENS, OPENAI_API_KEY, SYSTEM_MESSAGE


async def process_input_message(
    input_message: str,
    user: discord.User,
    conversation_summary: list[dict]
) -> str:
    """
    Process an input message using OpenAI's GPT model.
    """
    try:
        logger.info("Sending prompt to OpenAI API.")

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
                "Failed to get response from OpenAI API: "
                "Invalid response format."
            )
            return "Sorry, an error occurred while processing the message."

        if response_content:
            logger.info("Received response from OpenAI API.")
            # Debugging: Log the raw response
            # logger.info(f"Raw API response: {response}")
            logger.info(f"Sent the response: {response_content}")

            conversation.append(
                {"role": "assistant", "content": response_content}
            )
            conversation_history[user.id] = conversation

            return response_content
        else:
            logger.error("OpenAI API error: No response text.")
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


    # Set the intents for the bot
    intents = discord.Intents.default()
    intents.typing = False
    intents.presences = False

    # Create a dictionary to store the last command timestamp for each user
    last_command_timestamps = {}
    last_command_count = {}

    # Create a dictionary to store conversation history for each user
    conversation_history = {}

    # Create the bot instance
    bot = discord.Client(intents=intents)

    # Create the OpenAI client instance
    client = OpenAI(
        api_key=OPENAI_API_KEY
    )

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
