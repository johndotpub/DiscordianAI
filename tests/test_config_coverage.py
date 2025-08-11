# Tests for config.py functionality
import os
import tempfile
from unittest.mock import MagicMock, patch

from src.config import get_error_messages, load_config, parse_arguments


class TestParseArguments:
    def test_parse_arguments_no_args(self):
        """Test argument parsing with no arguments."""
        with patch("sys.argv", ["test"]):
            args = parse_arguments()

            assert args.conf is None
            assert args.folder is None

    def test_parse_arguments_with_conf(self):
        """Test argument parsing with config file."""
        with patch("sys.argv", ["test", "--conf", "test_config.ini"]):
            args = parse_arguments()

            assert args.conf == "test_config.ini"
            assert args.folder is None

    def test_parse_arguments_with_folder(self):
        """Test argument parsing with folder."""
        with patch("sys.argv", ["test", "--folder", "/test/path"]):
            args = parse_arguments()

            assert args.conf is None
            assert args.folder == "/test/path"

    def test_parse_arguments_both(self):
        """Test argument parsing with both arguments."""
        with patch("sys.argv", ["test", "--conf", "config.ini", "--folder", "/path"]):
            args = parse_arguments()

            assert args.conf == "config.ini"
            assert args.folder == "/path"


class TestLoadConfig:
    def test_load_config_defaults_only(self):
        """Test config loading with defaults only."""
        config = load_config()

        # Check default values
        assert config["DISCORD_TOKEN"] is None
        assert config["ALLOWED_CHANNELS"] == []
        assert config["BOT_PRESENCE"] == "online"
        assert config["ACTIVITY_TYPE"] == "listening"
        assert config["ACTIVITY_STATUS"] == "Humans"
        assert config["OPENAI_API_KEY"] is None
        assert config["OPENAI_API_URL"] == "https://api.openai.com/v1/"
        assert config["PERPLEXITY_API_KEY"] is None
        assert config["PERPLEXITY_API_URL"] == "https://api.perplexity.ai"
        assert config["GPT_MODEL"] == "gpt-4o-mini"
        assert config["INPUT_TOKENS"] == 120000
        assert config["OUTPUT_TOKENS"] == 8000
        assert config["CONTEXT_WINDOW"] == 128000
        assert config["SYSTEM_MESSAGE"] == "You are a helpful assistant."
        # Removed unsupported GPT-5 parameters
        assert config["RATE_LIMIT"] == 10
        assert config["RATE_LIMIT_PER"] == 60
        assert config["LOG_FILE"] == "bot.log"
        assert config["LOG_LEVEL"] == "INFO"
        assert config["LOOKBACK_MESSAGES_FOR_CONSISTENCY"] == 6
        assert config["ENTITY_DETECTION_MIN_WORDS"] == 10
        assert config["MAX_HISTORY_PER_USER"] == 50
        assert config["USER_LOCK_CLEANUP_INTERVAL"] == 3600

    def test_load_config_with_file(self):
        """Test config loading from file."""
        # Create a temporary config file
        config_content = """[Discord]
DISCORD_TOKEN=test_token
ALLOWED_CHANNELS=general,test
BOT_PRESENCE=dnd
ACTIVITY_TYPE=playing
ACTIVITY_STATUS=test game

[Default]
OPENAI_API_KEY=test_api_key
PERPLEXITY_API_KEY=test_perplexity_key
GPT_MODEL=gpt-4
INPUT_TOKENS=50000
OUTPUT_TOKENS=2000
SYSTEM_MESSAGE=Test system message
; Removed unsupported GPT-5 parameters

[Limits]
RATE_LIMIT=5
RATE_LIMIT_PER=30

[Orchestrator]
LOOKBACK_MESSAGES_FOR_CONSISTENCY=10
ENTITY_DETECTION_MIN_WORDS=15
MAX_HISTORY_PER_USER=100
USER_LOCK_CLEANUP_INTERVAL=7200

[Logging]
LOG_FILE=test.log
LOG_LEVEL=DEBUG
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write(config_content)
            temp_config_path = f.name

        try:
            config = load_config(temp_config_path)

            # Verify values from file
            assert config["DISCORD_TOKEN"] == "test_token"  # noqa: S105
            assert config["ALLOWED_CHANNELS"] == ["general", "test"]
            assert config["BOT_PRESENCE"] == "dnd"
            assert config["ACTIVITY_TYPE"] == "playing"
            assert config["ACTIVITY_STATUS"] == "test game"
            assert config["OPENAI_API_KEY"] == "test_api_key"
            assert config["PERPLEXITY_API_KEY"] == "test_perplexity_key"
            assert config["GPT_MODEL"] == "gpt-4"
            assert config["INPUT_TOKENS"] == 50000
            assert config["OUTPUT_TOKENS"] == 2000
            assert config["SYSTEM_MESSAGE"] == "Test system message"
            # Unsupported GPT-5 parameters should not be present
            assert "REASONING_EFFORT" not in config or config.get("REASONING_EFFORT") is None
            assert "VERBOSITY" not in config or config.get("VERBOSITY") is None
            assert config["RATE_LIMIT"] == 5
            assert config["RATE_LIMIT_PER"] == 30
            assert config["LOOKBACK_MESSAGES_FOR_CONSISTENCY"] == 10
            assert config["ENTITY_DETECTION_MIN_WORDS"] == 15
            assert config["MAX_HISTORY_PER_USER"] == 100
            assert config["USER_LOCK_CLEANUP_INTERVAL"] == 7200
            assert config["LOG_FILE"] == "test.log"
            assert config["LOG_LEVEL"] == "DEBUG"

        finally:
            os.unlink(temp_config_path)

    def test_load_config_nonexistent_file(self):
        """Test config loading with nonexistent file."""
        config = load_config("nonexistent_file.ini")

        # Should return defaults when file doesn't exist
        assert config["DISCORD_TOKEN"] is None
        assert config["GPT_MODEL"] == "gpt-4o-mini"

    def test_load_config_with_base_folder(self):
        """Test config loading with base folder."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_content = """[Logging]
LOG_FILE=relative.log
"""
            config_path = os.path.join(temp_dir, "test.ini")
            with open(config_path, "w") as f:
                f.write(config_content)

            config = load_config("test.ini", temp_dir)

            # Should resolve relative paths with base_folder
            expected_log_path = os.path.join(temp_dir, "relative.log")
            assert config["LOG_FILE"] == expected_log_path

    def test_load_config_env_overrides(self):
        """Test environment variable overrides."""
        with patch.dict(
            os.environ,
            {
                "DISCORD_TOKEN": "env_token",
                "OPENAI_API_KEY": "env_api_key",
                "RATE_LIMIT": "20",
                "ALLOWED_CHANNELS": "channel1,channel2",
                "OUTPUT_TOKENS": "invalid_integer",  # Test invalid integer handling
            },
        ):
            with patch("src.config.logging.getLogger") as mock_logger:
                mock_logger.return_value = MagicMock()

                config = load_config()

                # Environment variables should override defaults
                assert config["DISCORD_TOKEN"] == "env_token"  # noqa: S105
                assert config["OPENAI_API_KEY"] == "env_api_key"
                assert config["RATE_LIMIT"] == 20
                assert config["ALLOWED_CHANNELS"] == ["channel1", "channel2"]

                # Invalid integer should trigger warning and use default
                mock_logger.return_value.warning.assert_called()
                assert config["OUTPUT_TOKENS"] == 8000  # Default value

    def test_load_config_integer_conversion(self):
        """Test integer conversion for various config values."""
        with patch.dict(
            os.environ,
            {
                "INPUT_TOKENS": "100000",
                "OUTPUT_TOKENS": "5000",
                "CONTEXT_WINDOW": "200000",
                "RATE_LIMIT": "15",
                "RATE_LIMIT_PER": "120",
                "LOOKBACK_MESSAGES_FOR_CONSISTENCY": "8",
                "ENTITY_DETECTION_MIN_WORDS": "20",
                "MAX_HISTORY_PER_USER": "75",
                "USER_LOCK_CLEANUP_INTERVAL": "1800",
            },
        ):
            config = load_config()

            assert config["INPUT_TOKENS"] == 100000
            assert config["OUTPUT_TOKENS"] == 5000
            assert config["CONTEXT_WINDOW"] == 200000
            assert config["RATE_LIMIT"] == 15
            assert config["RATE_LIMIT_PER"] == 120
            assert config["LOOKBACK_MESSAGES_FOR_CONSISTENCY"] == 8
            assert config["ENTITY_DETECTION_MIN_WORDS"] == 20
            assert config["MAX_HISTORY_PER_USER"] == 75
            assert config["USER_LOCK_CLEANUP_INTERVAL"] == 1800

    def test_load_config_absolute_paths(self):
        """Test handling of absolute paths."""
        with tempfile.TemporaryDirectory() as temp_dir:
            absolute_config = os.path.join(temp_dir, "absolute.ini")
            absolute_log = os.path.join(temp_dir, "absolute.log")

            config_content = f"""[Logging]
LOG_FILE={absolute_log}
"""
            with open(absolute_config, "w") as f:
                f.write(config_content)

            config = load_config(absolute_config, temp_dir)

            # Absolute paths should be preserved
            assert config["LOG_FILE"] == absolute_log

    def test_load_config_mixed_overrides(self):
        """Test combination of file and environment overrides."""
        config_content = """[Default]
OPENAI_API_KEY=file_api_key
GPT_MODEL=file_model

[Limits]
RATE_LIMIT=25
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write(config_content)
            temp_config_path = f.name

        try:
            with patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "env_api_key",  # Should override file value
                    "PERPLEXITY_API_KEY": "env_perplexity_key",  # Not in file
                },
            ):
                config = load_config(temp_config_path)

                # Env should override file
                assert config["OPENAI_API_KEY"] == "env_api_key"
                # File value should be used when no env override
                assert config["GPT_MODEL"] == "file_model"
                # Env value should be used when not in file
                assert config["PERPLEXITY_API_KEY"] == "env_perplexity_key"

        finally:
            os.unlink(temp_config_path)


class TestGetErrorMessages:
    def test_get_error_messages_structure(self):
        """Test error messages dictionary structure."""
        messages = get_error_messages()

        # Check that it's a dictionary
        assert isinstance(messages, dict)

        # Check for expected error message keys
        expected_keys = [
            "web_search_unavailable",
            "ai_service_unavailable",
            "no_response_generated",
            "both_services_unavailable",
            "configuration_error",
            "unexpected_error",
            "rate_limit_exceeded",
            "api_error",
            "message_too_long",
            "empty_message",
        ]

        for key in expected_keys:
            assert key in messages
            assert isinstance(messages[key], str)
            assert len(messages[key]) > 0

    def test_get_error_messages_content(self):
        """Test specific error message content."""
        messages = get_error_messages()

        # Test some specific messages contain expected content
        assert "web search" in messages["web_search_unavailable"].lower()
        assert "ai service" in messages["ai_service_unavailable"].lower()
        assert "response" in messages["no_response_generated"].lower()
        assert "rate limit" in messages["rate_limit_exceeded"].lower()
        assert "ai service" in messages["api_error"].lower()
        assert "long" in messages["message_too_long"].lower()
        assert "message" in messages["empty_message"].lower()

        # Check that messages have emoji indicators
        assert "🔍" in messages["web_search_unavailable"]
        assert "🤖" in messages["ai_service_unavailable"]
        assert "🔧" in messages["no_response_generated"]
        assert "⏱️" in messages["rate_limit_exceeded"]

    def test_get_error_messages_consistency(self):
        """Test that get_error_messages returns consistent results."""
        messages1 = get_error_messages()
        messages2 = get_error_messages()

        # Should return same content on multiple calls
        assert messages1 == messages2

        # Should be different object instances (not cached references)
        assert messages1 is not messages2
