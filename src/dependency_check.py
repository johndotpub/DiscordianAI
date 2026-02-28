#!/usr/bin/env python3
"""Early dependency validation to catch missing packages before main startup.

This module runs before any complex imports to ensure all required dependencies
are available, providing clear error messages if packages are missing.
"""

import logging
import sys


def check_dependencies() -> tuple[bool, list[str]]:
    """Check if all required dependencies are available.

    Returns:
        Tuple[bool, List[str]]: (success, list of missing packages)
    """
    missing_packages = []

    # Core dependencies
    dependencies = [
        ("discord", "discord.py"),
        ("openai", "openai"),
        ("websockets", "websockets"),
        ("requests", "requests"),
        ("bs4", "beautifulsoup4"),
    ]

    # Check each dependency (performance overhead acceptable for startup validation)
    for import_name, package_name in dependencies:
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package_name)

    return len(missing_packages) == 0, missing_packages


def main():
    """Main entry point for dependency checking."""
    # Set up basic logging for dependency check
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

    success, missing = check_dependencies()

    if not success:
        logger.error("Missing required packages: %s", ", ".join(missing))
        logger.error("Please install dependencies with:")
        logger.error("  pip install -r requirements.txt")
        logger.error("\nOr install individual packages:")
        for package in missing:
            logger.error("  pip install %s", package)
        sys.exit(1)

    logger.info("✓ All dependencies are available.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
