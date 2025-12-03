# Tests for api_validation.py functionality
import pytest

from src.api_validation import (
    PERPLEXITY_MODELS,
    VALID_OPENAI_URL_PATTERN,
    VALID_PERPLEXITY_URL_PATTERN,
    validate_full_config,
    validate_openai_api_key_format,
    validate_openai_config,
    validate_perplexity_api_key_format,
    validate_perplexity_config,
)


class TestAPIKeyFormatValidation:
    """Test API key format validation functions."""

    def test_validate_openai_api_key_format_valid(self):
        """Test valid OpenAI API key formats."""
        valid_keys = [
            "sk-" + "a" * 32,
            "sk-" + "A" * 32,
            "sk-" + "0" * 32,
            "sk-" + "aA0" * 20,  # Mixed case and numbers
        ]

        for key in valid_keys:
            is_valid, error_msg = validate_openai_api_key_format(key)
            assert is_valid, f"Key {key[:10]}... should be valid"
            assert error_msg is None

    def test_validate_openai_api_key_format_invalid(self):
        """Test invalid OpenAI API key formats."""
        invalid_keys = [
            "invalid-key",
            "sk-",  # Too short
            "sk-" + "a" * 10,  # Too short
            "pk-" + "a" * 32,  # Wrong prefix
            "SK-" + "a" * 32,  # Wrong case prefix
            "",  # Empty string (though None is valid)
            "sk-abc!@#",  # Invalid characters
        ]

        for key in invalid_keys:
            is_valid, error_msg = validate_openai_api_key_format(key)
            assert not is_valid, f"Key {key[:10]}... should be invalid"
            assert error_msg is not None
            assert "OpenAI API key" in error_msg
            assert "sk-" in error_msg

    def test_validate_openai_api_key_format_none(self):
        """Test None OpenAI API key (should be valid as optional)."""
        is_valid, error_msg = validate_openai_api_key_format(None)
        assert is_valid
        assert error_msg is None

    def test_validate_perplexity_api_key_format_valid(self):
        """Test valid Perplexity API key formats."""
        valid_keys = [
            "pplx-" + "a" * 32,
            "pplx-" + "A" * 32,
            "pplx-" + "0" * 32,
            "pplx-" + "aA0" * 20,  # Mixed case and numbers
        ]

        for key in valid_keys:
            is_valid, error_msg = validate_perplexity_api_key_format(key)
            assert is_valid, f"Key {key[:10]}... should be valid"
            assert error_msg is None

    def test_validate_perplexity_api_key_format_invalid(self):
        """Test invalid Perplexity API key formats."""
        invalid_keys = [
            "invalid-key",
            "pplx-",  # Too short
            "pplx-" + "a" * 10,  # Too short
            "ppl-" + "a" * 32,  # Wrong prefix
            "PPLX-" + "a" * 32,  # Wrong case prefix
            "",  # Empty string (though None is valid)
            "pplx-abc!@#",  # Invalid characters
        ]

        for key in invalid_keys:
            is_valid, error_msg = validate_perplexity_api_key_format(key)
            assert not is_valid, f"Key {key[:10]}... should be invalid"
            assert error_msg is not None
            assert "Perplexity API key" in error_msg
            assert "pplx-" in error_msg

    def test_validate_perplexity_api_key_format_none(self):
        """Test None Perplexity API key (should be valid as optional)."""
        is_valid, error_msg = validate_perplexity_api_key_format(None)
        assert is_valid
        assert error_msg is None


class TestOpenAIConfigValidation:
    """Test OpenAI configuration validation."""

    def test_validate_openai_config_valid(self):
        """Test validation of valid OpenAI configuration."""
        config = {
            "OPENAI_API_KEY": "sk-" + "a" * 32,
            "OPENAI_API_URL": "https://api.openai.com/v1/",
            "GPT_MODEL": "gpt-5-mini",
            "OUTPUT_TOKENS": 8000,
            "INPUT_TOKENS": 120000,
        }

        issues = validate_openai_config(config)
        # Should have no errors (may have INFO messages)
        errors = [issue for issue in issues if issue.startswith("ERROR:")]
        assert len(errors) == 0

    def test_validate_openai_config_invalid_url(self):
        """Test validation with invalid OpenAI API URL."""
        config = {
            "OPENAI_API_URL": "https://invalid-url.com",
            "GPT_MODEL": "gpt-5-mini",
        }

        issues = validate_openai_config(config)
        assert any("Invalid OpenAI API URL" in issue for issue in issues)

    def test_validate_openai_config_invalid_model(self):
        """Test validation with invalid GPT model."""
        config = {
            "GPT_MODEL": "gpt-4-invalid",
        }

        issues = validate_openai_config(config)
        assert any("Unknown GPT model" in issue for issue in issues)

    def test_validate_openai_config_invalid_api_key(self):
        """Test validation with invalid API key format."""
        config = {
            "OPENAI_API_KEY": "invalid-key-format",
        }

        issues = validate_openai_config(config)
        errors = [issue for issue in issues if issue.startswith("ERROR:")]
        assert len(errors) > 0
        assert any("Invalid OpenAI API key format" in error for error in errors)

    def test_validate_openai_config_high_token_limits(self):
        """Test validation with very high token limits."""
        config = {
            "OUTPUT_TOKENS": 60000,  # Very high
            "INPUT_TOKENS": 250000,  # Very high
        }

        issues = validate_openai_config(config)
        assert any("OUTPUT_TOKENS very high" in issue for issue in issues)
        assert any("INPUT_TOKENS very high" in issue for issue in issues)

    def test_validate_openai_config_missing_optional_fields(self):
        """Test validation with missing optional fields."""
        config = {}

        issues = validate_openai_config(config)
        # Should not error on missing optional fields
        errors = [issue for issue in issues if issue.startswith("ERROR:")]
        assert len(errors) == 0


class TestPerplexityConfigValidation:
    """Test Perplexity configuration validation."""

    def test_validate_perplexity_config_valid(self):
        """Test validation of valid Perplexity configuration."""
        config = {
            "PERPLEXITY_API_KEY": "pplx-" + "a" * 32,
            "PERPLEXITY_API_URL": "https://api.perplexity.ai",
        }

        issues = validate_perplexity_config(config)
        # Should have no errors (may have INFO messages)
        errors = [issue for issue in issues if issue.startswith("ERROR:")]
        assert len(errors) == 0

    def test_validate_perplexity_config_invalid_url(self):
        """Test validation with invalid Perplexity API URL."""
        config = {
            "PERPLEXITY_API_URL": "https://invalid-url.com",
        }

        issues = validate_perplexity_config(config)
        assert any("Invalid Perplexity API URL" in issue for issue in issues)

    def test_validate_perplexity_config_invalid_api_key(self):
        """Test validation with invalid API key format."""
        config = {
            "PERPLEXITY_API_KEY": "invalid-key-format",
        }

        issues = validate_perplexity_config(config)
        errors = [issue for issue in issues if issue.startswith("ERROR:")]
        assert len(errors) > 0
        assert any("Invalid Perplexity API key format" in error for error in errors)

    def test_validate_perplexity_config_missing_optional_fields(self):
        """Test validation with missing optional fields."""
        config = {}

        issues = validate_perplexity_config(config)
        # Should not error on missing optional fields
        errors = [issue for issue in issues if issue.startswith("ERROR:")]
        assert len(errors) == 0


class TestFullConfigValidation:
    """Test full configuration validation."""

    def test_validate_full_config_valid(self):
        """Test validation of complete valid configuration."""
        config = {
            "DISCORD_TOKEN": "test_token",
            "OPENAI_API_KEY": "sk-" + "a" * 32,
            "PERPLEXITY_API_KEY": "pplx-" + "a" * 32,
            "OPENAI_API_URL": "https://api.openai.com/v1/",
            "PERPLEXITY_API_URL": "https://api.perplexity.ai",
            "GPT_MODEL": "gpt-5-mini",
            "RATE_LIMIT": 10,
            "RATE_LIMIT_PER": 60,
            "ALLOWED_CHANNELS": ["general"],
        }

        warnings, errors = validate_full_config(config)
        assert len(errors) == 0

    def test_validate_full_config_missing_discord_token(self):
        """Test validation with missing Discord token."""
        config = {
            "OPENAI_API_KEY": "sk-" + "a" * 32,
        }

        warnings, errors = validate_full_config(config)
        assert len(errors) > 0
        assert any("DISCORD_TOKEN is required" in error for error in errors)

    def test_validate_full_config_no_api_keys(self):
        """Test validation with no API keys."""
        config = {
            "DISCORD_TOKEN": "test_token",
        }

        warnings, errors = validate_full_config(config)
        assert len(errors) > 0
        assert any("At least one API key" in error for error in errors)

    def test_validate_full_config_multiple_errors(self):
        """Test validation with multiple configuration errors."""
        config = {
            "DISCORD_TOKEN": "",  # Empty token
            "OPENAI_API_KEY": "invalid-key",
            "PERPLEXITY_API_KEY": "also-invalid",
            "OPENAI_API_URL": "invalid-url",
            "PERPLEXITY_API_URL": "also-invalid-url",
            "GPT_MODEL": "invalid-model",
            "RATE_LIMIT": -1,  # Invalid
            "RATE_LIMIT_PER": 0,  # Invalid
        }

        warnings, errors = validate_full_config(config)
        # Should have multiple errors
        assert len(errors) >= 2

    def test_validate_full_config_warnings_only(self):
        """Test validation with warnings but no errors."""
        config = {
            "DISCORD_TOKEN": "test_token",
            "OPENAI_API_KEY": "sk-" + "a" * 32,
            "OUTPUT_TOKENS": 60000,  # Very high (warning)
            "RATE_LIMIT": 150,  # Very high (warning)
            "ALLOWED_CHANNELS": [],  # Empty (warning)
        }

        warnings, errors = validate_full_config(config)
        assert len(errors) == 0
        assert len(warnings) > 0


class TestURLPatternValidation:
    """Test URL pattern validation."""

    def test_valid_openai_urls(self):
        """Test valid OpenAI URL patterns."""
        valid_urls = [
            "https://api.openai.com/v1/",
            "https://api.openai.com/v1",
            "https://api.openai.com/v2/",
        ]

        for url in valid_urls:
            assert VALID_OPENAI_URL_PATTERN.match(url), f"URL {url} should be valid"

    def test_invalid_openai_urls(self):
        """Test invalid OpenAI URL patterns."""
        invalid_urls = [
            "https://api.openai.com/",
            "https://invalid.com/v1/",
            "http://api.openai.com/v1/",  # HTTP not HTTPS
            "https://api.openai.com",
            "not-a-url",
        ]

        for url in invalid_urls:
            assert not VALID_OPENAI_URL_PATTERN.match(url), f"URL {url} should be invalid"

    def test_valid_perplexity_urls(self):
        """Test valid Perplexity URL patterns."""
        valid_urls = [
            "https://api.perplexity.ai",
            "https://api.perplexity.ai/",
        ]

        for url in valid_urls:
            assert VALID_PERPLEXITY_URL_PATTERN.match(url), f"URL {url} should be valid"

    def test_invalid_perplexity_urls(self):
        """Test invalid Perplexity URL patterns."""
        invalid_urls = [
            "https://api.perplexity.ai/v1/",
            "https://invalid.com",
            "http://api.perplexity.ai",  # HTTP not HTTPS
            "not-a-url",
        ]

        for url in invalid_urls:
            assert not VALID_PERPLEXITY_URL_PATTERN.match(url), f"URL {url} should be invalid"

