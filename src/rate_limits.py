async def check_rate_limit(
    user: discord.User,
    logger: logging.Logger = None
) -> bool:
    """
    Check if a user has exceeded the rate limit for sending messages.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    try:
        current_time = time.time()
        last_command_timestamp = last_command_timestamps.get(user.id, 0)
        last_command_count_user = last_command_count.get(user.id, 0)

        if current_time - last_command_timestamp > RATE_LIMIT_PER:
            last_command_timestamps[user.id] = current_time
            last_command_count[user.id] = 1
            logger.info(f"Rate limit passed for user: {user}")
            return True

        if last_command_count_user < RATE_LIMIT:
            last_command_count[user.id] += 1
            logger.info(f"Rate limit passed for user: {user}")
            return True

        logger.info(f"Rate limit exceeded for user: {user}")
        return False

    except Exception as e:
        logger.error(f"Error checking rate limit: {e}")
        raise