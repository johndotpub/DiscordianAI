"""Main entry point for DiscordianAI bot with robust error handling and logging.

This module provides the primary entry point for the Discord bot, handling
command-line argument parsing, configuration loading, logging setup, and
bot initialization with comprehensive error recovery.
"""

import logging
import os
import sys
from typing import NoReturn

from .api_validation import log_validation_results
from .bot import run_bot
from .config import load_config, parse_arguments


def setup_early_logging() -> logging.Logger:
    """Set up basic logging before configuration is loaded.

    This ensures that any errors during configuration loading are properly logged.
    The logging configuration will be updated later once the config is loaded.

    Returns:
        logging.Logger: Early logger instance for startup phases
    """
    # Set up basic logging to stderr for early startup
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    logger = logging.getLogger("discordianai.startup")
    logger.info("Early logging initialized - starting DiscordianAI bot")
    return logger


def setup_production_logging(config: dict, logger: logging.Logger) -> None:
    """Configure production logging based on loaded configuration.

    Reconfigures logging to use the settings from the config file,
    including log file location and verbosity level.

    Args:
        config (dict): Configuration dictionary with LOG_FILE and LOG_LEVEL
        logger (logging.Logger): Early logger to log the transition

    Raises:
        Exception: If logging configuration fails
    """
    try:
        log_file = config["LOG_FILE"]
        log_level = config["LOG_LEVEL"].upper()

        # Validate log level
        numeric_level = getattr(logging, log_level, None)
        if numeric_level is None:
            logger.warning(f"Invalid log level '{log_level}', defaulting to INFO")
            numeric_level = logging.INFO
            log_level = "INFO"

        # Ensure log directory exists
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            logger.info(f"Created log directory: {log_dir}")

        # Reconfigure logging with production settings
        logging.basicConfig(
            filename=log_file,
            level=numeric_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            force=True,  # Override existing configuration
        )

        # Also add console handler if we're not in a daemon mode
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)  # Only warnings and errors to console
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )

        root_logger = logging.getLogger()
        root_logger.addHandler(console_handler)

        logger.info(f"Production logging configured: file={log_file}, level={log_level}")

    except Exception:
        logger.exception("Failed to configure production logging")
        logger.warning("Continuing with basic logging configuration")
        # Don't raise - better to continue with basic logging than fail


def validate_critical_config(config: dict, logger: logging.Logger) -> None:
    """Validate critical configuration before starting the bot.

    Ensures that essential configuration is present and valid to prevent
    runtime failures after the bot has started.

    Args:
        config (dict): Configuration dictionary to validate
        logger (logging.Logger): Logger for validation messages

    Raises:
        ValueError: If critical configuration is missing or invalid
    """
    errors = []
    warnings = []

    # Check Discord token
    if not config.get("DISCORD_TOKEN"):
        errors.append("DISCORD_TOKEN is required but not provided")

    # Check API keys - at least one must be present
    has_openai = bool(config.get("OPENAI_API_KEY"))
    has_perplexity = bool(config.get("PERPLEXITY_API_KEY"))

    if not has_openai and not has_perplexity:
        errors.append(
            "At least one API key is required: provide either OPENAI_API_KEY (OpenAI) "
            "or PERPLEXITY_API_KEY (Perplexity) or both"
        )

    # Validate rate limiting settings
    try:
        rate_limit = int(config.get("RATE_LIMIT", 10))
        rate_limit_per = int(config.get("RATE_LIMIT_PER", 60))

        if rate_limit <= 0:
            errors.append("RATE_LIMIT must be positive")
        if rate_limit_per <= 0:
            errors.append("RATE_LIMIT_PER must be positive")
        if rate_limit > 100:
            warnings.append(
                f"RATE_LIMIT is very high ({rate_limit}) - consider lowering to prevent API abuse"
            )

    except (ValueError, TypeError):
        errors.append("RATE_LIMIT and RATE_LIMIT_PER must be valid integers")

    # Validate token limits
    try:
        output_tokens = int(config.get("OUTPUT_TOKENS", 8000))
        if output_tokens <= 0:
            errors.append("OUTPUT_TOKENS must be positive")
        if output_tokens > 50000:
            warnings.append(
                f"OUTPUT_TOKENS is very high ({output_tokens}) - may cause API costs/limits"
            )
    except (ValueError, TypeError):
        errors.append("OUTPUT_TOKENS must be a valid integer")

    # Check allowed channels
    allowed_channels = config.get("ALLOWED_CHANNELS", [])
    if not allowed_channels:
        warnings.append("No ALLOWED_CHANNELS configured - bot will not respond in any channels")

    # Log warnings
    for warning in warnings:
        logger.warning(f"Configuration warning: {warning}")

    # Raise error if critical issues found
    if errors:
        error_msg = "Critical configuration errors found:\n" + "\n".join(
            f"  - {error}" for error in errors
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    logger.info("Configuration validation passed - all critical settings are valid")


def handle_unhandled_exception(exc_type, exc_value, exc_traceback, logger: logging.Logger) -> None:
    """Global exception handler for unhandled exceptions with comprehensive logging.

    Handles keyboard interrupts gracefully and logs all other unhandled exceptions
    with full stack traces for debugging.

    Args:
        exc_type: Exception type
        exc_value: Exception value
        exc_traceback: Exception traceback
        logger: Logger instance for error reporting
    """
    # Handle keyboard interrupts gracefully (Ctrl+C)
    if issubclass(exc_type, KeyboardInterrupt):
        logger.info("Bot shutdown requested by user (KeyboardInterrupt)")
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Log all other unhandled exceptions with full context
    logger.critical(
        "UNHANDLED EXCEPTION - Bot crashed unexpectedly",
        exc_info=(exc_type, exc_value, exc_traceback),
    )

    # Also print to stderr as fallback
    # Use logging instead of print to avoid potential information leakage
    logging.getLogger(__name__).critical(f"Unhandled exception {exc_type.__name__}: {exc_value}")


def main() -> NoReturn:
    """Main entry point for the DiscordianAI bot.

    Handles the complete bot startup sequence including:
    1. Early logging setup
    2. Command-line argument parsing
    3. Configuration loading and validation
    4. Production logging configuration
    5. Global exception handler setup
    6. Bot initialization and startup

    This function implements a robust startup sequence with comprehensive
    error handling and logging at each step.

    Returns:
        NoReturn: This function runs indefinitely until the bot is stopped

    Raises:
        SystemExit: If critical initialization fails
    """
    # Step 1: Set up early logging before anything else
    early_logger = setup_early_logging()

    try:
        # Step 2: Parse command-line arguments
        early_logger.info("Parsing command-line arguments")
        args = parse_arguments()
        early_logger.debug(
            f"Arguments parsed: conf={args.conf}, folder={getattr(args, 'folder', None)}"
        )

        # Step 3: Load configuration (with early logging available for errors)
        early_logger.info("Loading configuration...")
        config = load_config(args.conf, getattr(args, "folder", None))
        early_logger.info("Configuration loaded successfully")

        # Step 4: Set up production logging based on config
        early_logger.info("Configuring production logging...")
        setup_production_logging(config, early_logger)

        # Get the properly configured logger
        logger = logging.getLogger("discordianai.main")
        logger.info("=== DiscordianAI Bot Starting ===")

        # Step 5: Validate critical configuration
        logger.info("Validating configuration...")
        validate_critical_config(config, logger)

        # Step 5.1: Validate API parameters
        logger.info("Validating API parameters...")
        api_validation_passed = log_validation_results(config, logger)
        if not api_validation_passed:
            logger.warning("API validation found issues, but continuing with startup")

        # Step 5.2: Run startup health checks (optional)
        logger.info("Running startup health checks...")
        try:
            # We'll run health checks after bot initialization since we need the clients
            # This is a placeholder for now - actual health checks run in bot startup
            logger.info("Health checks will run after bot initialization")
        except Exception as e:
            logger.warning(f"Startup health checks failed: {e}, but continuing with startup")

        # Step 6: Set up global exception handler (now with proper logging)
        def exception_handler(exc_type, exc_value, exc_traceback):
            handle_unhandled_exception(exc_type, exc_value, exc_traceback, logger)

        sys.excepthook = exception_handler
        logger.info("Global exception handler configured")

        # Step 7: Start the bot (this blocks until the bot stops)
        logger.info("Starting Discord bot...")
        run_bot(config)

    except KeyboardInterrupt:
        try:
            # Try to use the configured logger first
            logger.info("Bot startup interrupted by user")
        except NameError:
            # Fall back to early logger if main logger not initialized
            early_logger.info("Bot startup interrupted by user")
        sys.exit(0)

    except Exception as e:
        # Use appropriate logger based on where we are in startup
        try:
            logger.critical(f"Fatal error during bot startup: {e}", exc_info=True)
        except NameError:
            early_logger.critical(f"Fatal error during bot startup: {e}", exc_info=True)

        # Use logging for security instead of print statements
        logging.getLogger(__name__).critical(f"Bot startup failed: {e}")
        logging.getLogger(__name__).critical("Check the logs for detailed error information.")
        sys.exit(1)


if __name__ == "__main__":
    main()
