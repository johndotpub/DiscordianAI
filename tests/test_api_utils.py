"""Comprehensive tests for src/api_utils.py - API utility functions and builders.

This test suite covers:
- OpenAIParams builder class with all methods
- PerplexityParams builder class with all methods
- GPT model validation
- API response utilities
- API call building and logging
"""

from unittest.mock import Mock

from src.api_utils import (
    APICallBuilder,
    OpenAIParams,
    PerplexityParams,
    log_api_call,
    log_api_response,
    safe_extract_response_content,
    validate_gpt_model,
)


class TestOpenAIParams:
    """Test the OpenAIParams builder class."""

    def test_init_basic(self):
        """Test basic initialization."""
        builder = OpenAIParams("gpt-4", 1000)
        params = builder.build()

        assert params["model"] == "gpt-4"
        assert params["max_tokens"] == 1000
        assert len(params) == 2

    def test_add_messages(self):
        """Test adding messages to OpenAI parameters."""
        builder = OpenAIParams("gpt-4", 1000)
        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        result = builder.add_messages("System prompt", conversation, "How are you?")
        params = result.build()

        assert "messages" in params
        assert len(params["messages"]) == 4  # system + 2 conversation + user
        assert params["messages"][0]["role"] == "system"
        assert params["messages"][0]["content"] == "System prompt"
        assert params["messages"][-1]["role"] == "user"
        assert params["messages"][-1]["content"] == "How are you?"

    def test_add_messages_empty_conversation(self):
        """Test adding messages with empty conversation history."""
        builder = OpenAIParams("gpt-4", 1000)
        result = builder.add_messages("System prompt", [], "User message")
        params = result.build()

        assert len(params["messages"]) == 2  # system + user only
        assert params["messages"][0]["content"] == "System prompt"
        assert params["messages"][1]["content"] == "User message"

    def test_no_gpt5_parameters_supported(self):
        """GPT-5 specific parameters are not supported and should be absent."""
        builder = OpenAIParams("gpt-5", 1000)
        params = builder.build()
        assert "reasoning_effort" not in params
        assert "verbosity" not in params

    def test_non_gpt5_model_no_extra_params(self):
        builder = OpenAIParams("gpt-4", 1000)
        params = builder.build()
        assert "reasoning_effort" not in params
        assert "verbosity" not in params

    def test_no_param_helpers_present(self):
        builder = OpenAIParams("gpt-5", 1000)
        params = builder.build()
        assert "reasoning_effort" not in params
        assert "verbosity" not in params

    def test_builder_chain(self):
        """Test method chaining works correctly without GPT-5 helpers."""
        conversation = [{"role": "user", "content": "Test"}]
        params = OpenAIParams("gpt-5", 2000).add_messages("System", conversation, "Query").build()
        assert params["model"] == "gpt-5"
        assert params["max_tokens"] == 2000
        assert len(params["messages"]) == 3

    def test_build_returns_copy(self):
        """Test that build() returns a copy of parameters."""
        builder = OpenAIParams("gpt-4", 1000)
        params1 = builder.build()
        params2 = builder.build()
        params1["test"] = "modified"
        assert "test" not in params2
        assert params1 is not params2

    def test_openai_params_init_and_messages(self):
        builder = OpenAIParams("gpt-5", 2000)
        params = builder.add_messages("System", [], "Query").build()
        assert params["model"] == "gpt-5"
        assert params["max_tokens"] == 2000
        assert len(params["messages"]) == 2


class TestPerplexityParams:
    """Test the PerplexityParams builder class."""

    def test_init_with_model(self):
        """Test initialization with specific model."""
        builder = PerplexityParams("sonar-pro", 4000)
        params = builder.build()

        assert params["model"] == "sonar-pro"
        assert params["max_tokens"] == 4000
        assert params["temperature"] == 0.7

    def test_init_default_model(self):
        """Test initialization with default model."""
        builder = PerplexityParams()
        params = builder.build()

        assert params["model"] == "sonar-pro"
        assert params["max_tokens"] == 8000
        assert params["temperature"] == 0.7

    def test_init_none_model(self):
        """Test initialization with None model uses default."""
        builder = PerplexityParams(None, 5000)
        params = builder.build()

        assert params["model"] == "sonar-pro"
        assert params["max_tokens"] == 5000

    def test_add_messages(self):
        """Test adding messages to Perplexity parameters."""
        builder = PerplexityParams("sonar")
        result = builder.add_messages("System prompt", "User query")
        params = result.build()

        assert "messages" in params
        assert len(params["messages"]) == 2
        assert params["messages"][0]["role"] == "system"
        assert params["messages"][0]["content"] == "System prompt"
        assert params["messages"][1]["role"] == "user"
        assert params["messages"][1]["content"] == "User query"

    def test_set_temperature_valid_range(self):
        """Test setting temperature within valid range."""
        builder = PerplexityParams()
        result = builder.set_temperature(0.5)
        params = result.build()

        assert params["temperature"] == 0.5

    def test_set_temperature_clamp_low(self):
        """Test temperature is clamped to minimum 0.0."""
        builder = PerplexityParams()
        result = builder.set_temperature(-0.5)
        params = result.build()

        assert params["temperature"] == 0.0

    def test_set_temperature_clamp_high(self):
        """Test temperature is clamped to maximum 1.0."""
        builder = PerplexityParams()
        result = builder.set_temperature(1.5)
        params = result.build()

        assert params["temperature"] == 1.0

    def test_set_temperature_edge_cases(self):
        """Test temperature edge cases (0.0 and 1.0)."""
        builder = PerplexityParams()

        params1 = builder.set_temperature(0.0).build()
        assert params1["temperature"] == 0.0

        params2 = builder.set_temperature(1.0).build()
        assert params2["temperature"] == 1.0

    def test_builder_chain(self):
        """Test method chaining works correctly."""
        params = (
            PerplexityParams("sonar", 6000)
            .add_messages("System", "Query")
            .set_temperature(0.3)
            .build()
        )

        assert params["model"] == "sonar"
        assert params["max_tokens"] == 6000
        assert params["temperature"] == 0.3
        assert len(params["messages"]) == 2

    def test_build_returns_copy(self):
        """Test that build() returns a copy of parameters."""
        builder = PerplexityParams()
        params1 = builder.build()
        params2 = builder.build()

        params1["test"] = "modified"
        assert "test" not in params2
        assert params1 is not params2


class TestValidateGptModel:
    """Test GPT model validation function."""

    def test_valid_models(self):
        """Test validation of all valid models."""
        valid_models = ["gpt-5", "gpt-4o", "gpt-4o-mini", "gpt-4", "gpt-4-turbo"]

        for model in valid_models:
            assert validate_gpt_model(model) is True

    def test_invalid_model(self):
        """Test validation of invalid model."""
        assert validate_gpt_model("gpt-3") is False
        assert validate_gpt_model("invalid-model") is False
        assert validate_gpt_model("") is False

    def test_invalid_model_with_logger(self):
        """Test invalid model logs warning when logger provided."""
        mock_logger = Mock()

        result = validate_gpt_model("gpt-3", mock_logger)

        assert result is False
        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "gpt-3" in warning_msg
        assert "Known models:" in warning_msg

    def test_valid_model_no_warning(self):
        """Test valid model doesn't log warning."""
        mock_logger = Mock()

        result = validate_gpt_model("gpt-4", mock_logger)

        assert result is True
        mock_logger.warning.assert_not_called()

    def test_case_sensitivity(self):
        """Test model validation is case sensitive."""
        assert validate_gpt_model("GPT-4") is False
        assert validate_gpt_model("gpt-4") is True


class TestAPIUtilities:
    """Test API utility functions."""

    def test_log_api_call(self):
        """Test API call logging."""
        mock_logger = Mock()

        log_api_call(mock_logger, "OpenAI", "gpt-4", 100, 5)

        mock_logger.info.assert_called_once()
        log_msg = mock_logger.info.call_args[0][0]
        assert "OpenAI" in log_msg
        assert "gpt-4" in log_msg
        assert "API call" in log_msg

    def test_log_api_response(self):
        """Test API response logging."""
        mock_logger = Mock()

        log_api_response(mock_logger, "Perplexity", 500, {"finish_reason": "stop"})

        mock_logger.info.assert_called_once()
        log_msg = mock_logger.info.call_args[0][0]
        assert "Perplexity" in log_msg
        assert "500 characters" in log_msg

    def test_log_api_response_no_metadata(self):
        """Test API response logging without metadata."""
        mock_logger = Mock()

        log_api_response(mock_logger, "OpenAI", 250)

        mock_logger.info.assert_called_once()
        log_msg = mock_logger.info.call_args[0][0]
        assert "OpenAI" in log_msg
        assert "250 characters" in log_msg

    def test_safe_extract_response_content_valid(self):
        """Test safe response content extraction with valid response."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Test response"

        result = safe_extract_response_content(mock_response)

        assert result == "Test response"

    def test_safe_extract_response_content_valid_with_service(self):
        """Test safe response content extraction with service name."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "  Response with whitespace  "

        result = safe_extract_response_content(mock_response, "OpenAI")

        assert result == "Response with whitespace"

    def test_safe_extract_response_content_empty_choices(self):
        """Test safe response content extraction with empty choices."""
        mock_response = Mock()
        mock_response.choices = []

        result = safe_extract_response_content(mock_response)

        assert result is None

    def test_safe_extract_response_content_no_content(self):
        """Test safe response content extraction with no content."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = None

        result = safe_extract_response_content(mock_response)

        assert result is None

    def test_safe_extract_response_content_empty_content(self):
        """Test safe response content extraction with empty content."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = ""

        result = safe_extract_response_content(mock_response)

        assert result is None

    def test_safe_extract_response_content_exception(self):
        """Test safe response content extraction handles exceptions."""
        mock_response = Mock()
        mock_response.choices = None  # This will cause AttributeError

        result = safe_extract_response_content(mock_response)

        assert result is None


class TestAPICallBuilder:
    """Test the APICallBuilder class."""

    def test_openai_call_basic(self):
        """Test basic OpenAI call building."""
        params = APICallBuilder.openai_call("gpt-4", "You are helpful", [], "Hello", 1000)

        assert params["model"] == "gpt-4"
        assert params["max_tokens"] == 1000
        assert "messages" in params
        assert len(params["messages"]) == 2  # system + user

    def test_openai_call_with_conversation(self):
        """Test OpenAI call with conversation history."""
        conversation = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        params = APICallBuilder.openai_call(
            "gpt-4", "System prompt", conversation, "How are you?", 1500
        )

        assert params["model"] == "gpt-4"
        assert params["max_tokens"] == 1500
        assert len(params["messages"]) == 4  # system + conversation + user

    def test_openai_call_builds_supported_params_only(self):
        params = APICallBuilder.openai_call("gpt-5", "System", [], "Hello", 1000)
        assert params["model"] == "gpt-5"
        assert params["max_tokens"] == 1000
        assert "reasoning_effort" not in params
        assert "verbosity" not in params

    def test_perplexity_call_basic(self):
        """Test basic Perplexity call building."""
        params = APICallBuilder.perplexity_call("System", "Hello", model="sonar")

        assert params["model"] == "sonar"
        assert params["max_tokens"] == 8000
        assert "messages" in params
        assert len(params["messages"]) == 2

    def test_perplexity_call_custom_params(self):
        """Test Perplexity call with custom parameters."""
        params = APICallBuilder.perplexity_call(
            "System", "Hello", model="sonar-pro", max_tokens=5000, temperature=0.3
        )

        assert params["model"] == "sonar-pro"
        assert params["max_tokens"] == 5000
        assert params["temperature"] == 0.3

    def test_perplexity_call_default_model(self):
        """Test Perplexity call with default model."""
        params = APICallBuilder.perplexity_call("System", "Hello")

        assert params["model"] == "sonar-pro"  # Default fallback
        assert params["max_tokens"] == 8000
        assert params["temperature"] == 0.7

    def test_static_methods_independent(self):
        """Test that static methods work independently."""
        openai_params = APICallBuilder.openai_call("gpt-4", "System", [], "Query", 1000)
        perplexity_params = APICallBuilder.perplexity_call("System", "Query", model="sonar")

        # Both should work independently
        assert openai_params["model"] == "gpt-4"
        assert perplexity_params["model"] == "sonar"
        assert openai_params != perplexity_params


class TestAPIUtilitiesFunctions:
    """Test additional API utility functions."""

    def test_extract_api_error_info_rate_limit(self):
        """Test extracting rate limit error information."""
        from src.api_utils import extract_api_error_info

        error = Exception("Rate limit exceeded, retry after 60 seconds")
        info = extract_api_error_info(error)

        assert info["error_type"] == "Exception"
        assert info["is_rate_limit"] is True
        assert info["retry_recommended"] is True
        assert info["retry_after"] == 60

    def test_extract_api_error_info_timeout(self):
        """Test extracting timeout error information."""
        from src.api_utils import extract_api_error_info

        error = Exception("Request timed out after 30 seconds")
        info = extract_api_error_info(error)

        assert info["is_timeout"] is True
        assert info["retry_recommended"] is True
        assert info["retry_after"] is None

    def test_extract_api_error_info_auth(self):
        """Test extracting authentication error information."""
        from src.api_utils import extract_api_error_info

        error = Exception("401 Unauthorized: Invalid API key")
        info = extract_api_error_info(error)

        assert info["is_auth_error"] is True
        assert info["retry_recommended"] is False

    def test_extract_api_error_info_server_error(self):
        """Test extracting server error information."""
        from src.api_utils import extract_api_error_info

        error = Exception("500 Internal Server Error")
        info = extract_api_error_info(error)

        assert info["is_server_error"] is True
        assert info["retry_recommended"] is True

    def test_build_system_message_no_context(self):
        """Test building system message without context."""
        from src.api_utils import build_system_message

        result = build_system_message("Base message")
        assert result == "Base message"

    def test_build_system_message_with_context(self):
        """Test building system message with context."""
        from src.api_utils import build_system_message

        context = {
            "current_time": "2024-01-01 12:00:00",
            "user_preferences": "formal tone",
            "conversation_context": "technical discussion",
        }

        result = build_system_message("Base message", context)

        assert "Base message" in result
        assert "Current time: 2024-01-01 12:00:00" in result
        assert "User preferences: formal tone" in result
        assert "Context: technical discussion" in result

    def test_extract_usage_stats(self):
        """Test extracting usage statistics from response."""
        from src.api_utils import extract_usage_stats

        mock_response = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        stats = extract_usage_stats(mock_response)

        assert stats["prompt_tokens"] == 100
        assert stats["completion_tokens"] == 50
        assert stats["total_tokens"] == 150

    def test_extract_usage_stats_no_usage(self):
        """Test extracting usage statistics when no usage data."""
        from src.api_utils import extract_usage_stats

        mock_response = Mock()
        del mock_response.usage  # Remove usage attribute

        stats = extract_usage_stats(mock_response)

        assert stats == {}

    def test_estimate_token_count(self):
        """Test token count estimation."""
        from src.api_utils import estimate_token_count

        # Test various text lengths
        assert estimate_token_count("") == 0
        assert estimate_token_count("test") == 1  # 4 chars = 1 token
        assert estimate_token_count("this is a test message") == 5  # ~22 chars = 5 tokens

    def test_validate_token_limits_valid(self):
        """Test token limit validation with valid inputs."""
        from src.api_utils import validate_token_limits

        # 1000 prompt + 500 completion = 1500 <= 4000 context window
        result = validate_token_limits(1000, 500, 4000)
        assert result is True

    def test_validate_token_limits_invalid(self):
        """Test token limit validation with invalid inputs."""
        from src.api_utils import validate_token_limits

        # 3000 prompt + 2000 completion = 5000 > 4000 context window
        result = validate_token_limits(3000, 2000, 4000)
        assert result is False

    def test_validate_token_limits_exact_limit(self):
        """Test token limit validation at exact limit."""
        from src.api_utils import validate_token_limits

        # Exactly at the limit
        result = validate_token_limits(2000, 2000, 4000)
        assert result is True
