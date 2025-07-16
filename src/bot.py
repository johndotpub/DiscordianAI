# Standard library imports
import logging
import re

# Third-party imports
import discord
from openai import OpenAI

from .conversations import get_conversation_summary
from .discord_bot import set_activity_status
from .openai_processing import process_input_message
from .rate_limits import RateLimiter, check_rate_limit


def initialize_bot_and_dependencies(config):
    logger = logging.getLogger("discordianai.bot")
    logger.setLevel(getattr(logging, config["LOG_LEVEL"].upper(), logging.INFO))
    intents = discord.Intents.default()
    intents.typing = False
    intents.presences = False
    bot = discord.Client(intents=intents)
    client = OpenAI(api_key=config["API_KEY"], base_url=config["API_URL"])
    rate_limiter = RateLimiter()
    dependencies = {
        "logger": logger,
        "bot": bot,
        "client": client,
        "rate_limiter": rate_limiter,
        "CONVERSATION_HISTORY": {},
        "ALLOWED_CHANNELS": config["ALLOWED_CHANNELS"],
        "BOT_PRESENCE": config["BOT_PRESENCE"],
        "ACTIVITY_TYPE": config["ACTIVITY_TYPE"],
        "ACTIVITY_STATUS": config["ACTIVITY_STATUS"],
        "DISCORD_TOKEN": config["DISCORD_TOKEN"],
        "RATE_LIMIT": config["RATE_LIMIT"],
        "RATE_LIMIT_PER": config["RATE_LIMIT_PER"],
        "GPT_MODEL": config["GPT_MODEL"],
        "SYSTEM_MESSAGE": config["SYSTEM_MESSAGE"],
        "OUTPUT_TOKENS": config["OUTPUT_TOKENS"],
    }
    return dependencies


async def process_dm_message(message, deps):
    logger = deps["logger"]
    rate_limiter = deps["rate_limiter"]
    RATE_LIMIT = deps["RATE_LIMIT"]
    RATE_LIMIT_PER = deps["RATE_LIMIT_PER"]
    CONVERSATION_HISTORY = deps["CONVERSATION_HISTORY"]
    client = deps["client"]
    GPT_MODEL = deps["GPT_MODEL"]
    SYSTEM_MESSAGE = deps["SYSTEM_MESSAGE"]
    OUTPUT_TOKENS = deps["OUTPUT_TOKENS"]
    logger.info(f"Received DM from {message.author}: {message.content}")
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
        message.content,
        message.author,
        conversation_summary,
        CONVERSATION_HISTORY,
        logger,
        client,
        GPT_MODEL,
        SYSTEM_MESSAGE,
        OUTPUT_TOKENS,
    )
    await send_split_message(message.channel, response, deps)


async def process_channel_message(message, deps):
    logger = deps["logger"]
    rate_limiter = deps["rate_limiter"]
    RATE_LIMIT = deps["RATE_LIMIT"]
    RATE_LIMIT_PER = deps["RATE_LIMIT_PER"]
    CONVERSATION_HISTORY = deps["CONVERSATION_HISTORY"]
    client = deps["client"]
    GPT_MODEL = deps["GPT_MODEL"]
    SYSTEM_MESSAGE = deps["SYSTEM_MESSAGE"]
    OUTPUT_TOKENS = deps["OUTPUT_TOKENS"]
    logger.info(
        "Received message in {} from {}: {}".format(
            str(message.channel),
            str(message.author),
            re.sub(r"<@\d+>", "", message.content),
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
        message.content,
        message.author,
        conversation_summary,
        CONVERSATION_HISTORY,
        logger,
        client,
        GPT_MODEL,
        SYSTEM_MESSAGE,
        OUTPUT_TOKENS,
    )
    await send_split_message(message.channel, response, deps)


def find_split_index(message, middle_index):
    split_index = message.rfind("\n", 0, middle_index)
    if split_index == -1:
        split_index = middle_index
    return split_index


def adjust_for_code_block(message, before_split, middle_index):
    if before_split.count("```") % 2 != 0:
        split_index = message.find("\n", middle_index)
        if split_index == -1:
            split_index = middle_index
        before_split = message[:split_index]
        after_split = message[split_index:]
        return before_split, after_split
    else:
        after_split = message[len(before_split) :]
        return before_split, after_split


async def send_split_message(channel, message, deps):
    if len(message) <= 2000:
        await channel.send(message)
        return
    middle_index = len(message) // 2
    split_index = find_split_index(message, middle_index)
    before_split = message[:split_index]
    after_split = message[split_index:]
    before_split, after_split = adjust_for_code_block(message, before_split, middle_index)
    message_part1 = before_split.strip()
    message_part2 = after_split.strip()
    await channel.send(message_part1)
    await send_split_message(channel, message_part2, deps)


def register_event_handlers(bot, deps):
    @bot.event
    async def on_ready():
        logger = deps["logger"]
        BOT_PRESENCE = deps["BOT_PRESENCE"]
        ACTIVITY_TYPE = deps["ACTIVITY_TYPE"]
        ACTIVITY_STATUS = deps["ACTIVITY_STATUS"]
        logger.info(f"We have logged in as {bot.user}")
        logger.info(f"Configured bot presence: {BOT_PRESENCE}")
        logger.info(f"Configured activity type: {ACTIVITY_TYPE}")
        logger.info(f"Configured activity status: {ACTIVITY_STATUS}")
        activity = set_activity_status(ACTIVITY_TYPE, ACTIVITY_STATUS)
        await bot.change_presence(activity=activity, status=discord.Status(BOT_PRESENCE))

    @bot.event
    async def on_disconnect():
        deps["logger"].info("Bot has disconnected")

    @bot.event
    async def on_resumed():
        deps["logger"].info("Bot has resumed session")

    @bot.event
    async def on_shard_ready(shard_id):
        deps["logger"].info(f"Shard {shard_id} is ready")

    @bot.event
    async def on_message(message: discord.Message):
        try:
            if message.author == bot.user:
                return
            if isinstance(message.channel, discord.DMChannel):
                await process_dm_message(message, deps)
            elif (
                isinstance(message.channel, discord.TextChannel)
                and message.channel.name in deps["ALLOWED_CHANNELS"]
                and bot.user in message.mentions
            ):
                await process_channel_message(message, deps)
        except Exception as e:
            deps["logger"].error(f"An error occurred in on_message: {e}")


def run_bot(config):
    deps = initialize_bot_and_dependencies(config)
    register_event_handlers(deps["bot"], deps)
    deps["bot"].run(deps["DISCORD_TOKEN"])
