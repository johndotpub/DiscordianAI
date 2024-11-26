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
