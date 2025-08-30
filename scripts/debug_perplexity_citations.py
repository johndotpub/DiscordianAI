#!/usr/bin/env python3
"""Debug script for Perplexity citation extraction.

Usage: python scripts/debug_perplexity_citations.py [config_file]
Example: python scripts/debug_perplexity_citations.py bender.ini
"""

import argparse
import asyncio
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import logging

from openai import OpenAI

from config import load_config
from conversation_manager import ThreadSafeConversationManager
from perplexity_processing import process_perplexity_message


def setup_logging():
    """Set up detailed logging for debugging."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


async def debug_perplexity_citations(config_file: str):
    """Debug Perplexity citation extraction with real API."""
    print("🔍 Debugging Perplexity Citation Extraction")
    print("=" * 50)
    print(f"📁 Using config: {config_file}")

    # Load configuration
    try:
        config = load_config(config_file)
        print("✅ Configuration loaded successfully")
    except Exception as e:
        print(f"❌ Failed to load {config_file}: {e}")
        return False

    # Check API key
    if not config.get("PERPLEXITY_API_KEY"):
        print(f"❌ PERPLEXITY_API_KEY not found in {config_file}")
        return False

    print("✅ Perplexity API key found")

    # Set up logging
    setup_logging()
    logger = logging.getLogger("test")

    # Create Perplexity client
    try:
        perplexity_client = OpenAI(
            api_key=config["PERPLEXITY_API_KEY"], base_url=config["PERPLEXITY_API_URL"]
        )
        print("✅ Perplexity client created")
    except Exception as e:
        print(f"❌ Failed to create Perplexity client: {e}")
        return False

    # Create test components
    class MockUser:
        def __init__(self):
            self.id = 99999

    user = MockUser()
    conversation_manager = ThreadSafeConversationManager()

    # Test queries that should generate citations
    test_queries = [
        "What's the recent news about DDOG stock?",
        "What are the latest AI developments in 2025?",
        "Current weather in San Francisco",
        "Recent Tesla stock performance",
    ]

    print(f"\n🧪 Testing {len(test_queries)} queries...")
    print("-" * 50)

    success_count = 0

    for i, query in enumerate(test_queries, 1):
        print(f"\n🔍 Test {i}: '{query}'")

        try:
            result = await process_perplexity_message(
                query,
                user,
                conversation_manager,
                logger,
                perplexity_client,
                config.get("SYSTEM_MESSAGE", "You are a helpful assistant with web search."),
                1000,  # Shorter response for testing
                config.get("PERPLEXITY_MODEL", "sonar-pro"),
            )

            if result:
                response_text, suppress_embeds, embed_data = result

                print("  ✅ API call successful")
                print(f"  📝 Response: {len(response_text)} chars")
                print(f"  🔗 Has embed: {embed_data is not None}")

                if embed_data:
                    citations = embed_data["citations"]
                    embed = embed_data["embed"]
                    print(f"  📚 Citations: {len(citations)}")

                    for num, url in citations.items():
                        print(f"    [{num}]: {url[:60]}...")

                    # Check for clickable formatting
                    if "[[" in embed.description and "]](" in embed.description:
                        print("  ✅ Citations formatted as clickable hyperlinks!")
                        success_count += 1
                    else:
                        print("  ❌ Citations not clickable")
                else:
                    print("  ⚠️  No citations found (might be conversational query)")

            else:
                print("  ❌ API call failed")

        except Exception as e:
            print(f"  ❌ Error: {e}")

    print(f"\n📊 Results: {success_count}/{len(test_queries)} queries had clickable citations")

    if success_count > 0:
        print("🎉 Citation fix is working!")
        return True
    print("❌ Citation fix needs more work")
    return False


def main():
    """Main function with argument parsing."""
    parser = argparse.ArgumentParser(description="Test Perplexity citations with real API")
    parser.add_argument(
        "config", nargs="?", default="config.ini", help="Configuration file (default: config.ini)"
    )
    args = parser.parse_args()

    if not Path(args.config).exists():
        print(f"❌ Configuration file '{args.config}' not found")
        print("💡 Usage: python scripts/debug_perplexity_citations.py [config_file]")
        print("💡 Example: python scripts/debug_perplexity_citations.py bender.ini")
        sys.exit(1)

    success = asyncio.run(debug_perplexity_citations(args.config))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
