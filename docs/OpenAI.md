# OpenAI-Compatible Provider Guide (Ollama Cloud Default)

DiscordianAI talks to an OpenAI-compatible Chat Completions endpoint. The shipped default is
Ollama Cloud (`https://ollama.com/v1/`, model `deepseek-v4.1-flash:1017`); OpenAI itself is
fully supported as a non-default option. The same client, retry policy, and delivery path are
used for either provider.

## Supported Providers and Models

The bot does not gate provider model ids. Any non-empty `GPT_MODEL` is accepted and sent as
configured; the provider decides whether the name exists.

### Ollama Cloud (default)
- **Endpoint**: `https://ollama.com/v1/`
- **Model**: `deepseek-v4.1-flash:1017`
- **Reasoning effort**: `high` by default; `low`, `high`, and `max` are accepted by this
  model, and `none` disables thinking. Reasoning tokens count toward the output cap.

### OpenAI
- **Endpoint**: `https://api.openai.com/v1/`
- **Models**: any model the account can use, including current GPT names. The old
  family allowlist is gone; the provider decides which names are valid.
- **Key shape**: OpenAI keys start with `sk-`. Other compatible providers use their own
  formats and are accepted with a warning.

### Local Ollama
- **Endpoint**: `http(s)://localhost:11434/v1/` or `http(s)://127.0.0.1:11434/v1/`
- Use the model name installed locally.

## Configuration

### Basic Ollama Cloud Setup (default)
```ini
[Default]
# OpenAI-compatible chat configuration
OPENAI_API_KEY=your-ollama-cloud-api-key
OPENAI_API_URL=https://ollama.com/v1/
GPT_MODEL=deepseek-v4.1-flash:1017
REASONING_EFFORT=high

# Token limits
OUTPUT_TOKENS=16384
INPUT_TOKENS=250000
CONTEXT_WINDOW=1000000

# System message for personality
SYSTEM_MESSAGE=You are a helpful AI assistant with access to current information.
```

### Switching to OpenAI
Change the three provider values:
```ini
OPENAI_API_KEY=sk-your-openai-key
OPENAI_API_URL=https://api.openai.com/v1/
GPT_MODEL=<your-openai-model>
```

### Provider Notes
The bot uses standard Chat Completions parameters: `model`, `messages`, an output cap, and
optionally `reasoning_effort`. The cap is `max_tokens` on Ollama-compatible hosts
(`ollama.com`, `localhost`, `127.0.0.1`) and `max_completion_tokens` on every other
OpenAI-compatible host, including `api.openai.com`. It does not send sampling parameters
such as `temperature`. Ollama-compatible hosts also
receive `web_search` and `web_fetch` function tools when `WEB_TOOLS` is true; OpenAI endpoints
receive no tools. Cloud models generally do not support structured outputs, log
probabilities, or `tool_choice`; the bot does not request them.

## Operation Modes

### OpenAI-Compatible Only Mode
Disable Perplexity to use only the chat provider:
```ini
OPENAI_API_KEY=your-ollama-cloud-api-key
PERPLEXITY_API_KEY=
```

### Smart Hybrid Mode
Enable both for intelligent routing:
```ini
OPENAI_API_KEY=your-ollama-cloud-api-key
PERPLEXITY_API_KEY=your_perplexity_key_here
```

## Advanced Features

### Conversation Consistency
- **Metadata Tracking**: Each chat response includes model and service information
- **Follow-up Routing**: A short anaphoric or continuation follow-up inherits the previous route (including the chat provider) when the gate records one; other messages are decided from their own cues
- **Context Preservation**: Maintains conversation context across multiple exchanges

### Thread-Safe Architecture
- **Per-Conversation History**: Each guild channel, thread, or DM has isolated conversation history
- **Concurrent Processing**: Multiple conversations can proceed simultaneously without interference
- **Memory Management**: Automatic cleanup of old conversation data

### Error Handling & Fallbacks
- **Graceful Degradation**: If the chat provider fails, the system provides helpful error messages
- **Retry Logic**: Automatic retries for transient API failures
- **Logging**: Comprehensive logging for debugging and monitoring

## Usage Examples

### Conversational Queries (Auto-routed to the chat provider)
- `"Hello! How are you today?"`
- `"Can you help me write a Python function?"`
- `"What do you think about artificial intelligence?"`
- `"Write me a story about robots"`

### Technical Assistance
- `"Explain how recursion works in programming"`
- `"Help me debug this code: [code snippet]"`
- `"What's the difference between async and sync programming?"`

### Creative Tasks
- `"Write a poem about nature"`
- `"Create a marketing slogan for a tech startup"`
- `"Generate ideas for a sci-fi story"`

## Performance Optimization

### Token Management
```ini
# Adjust based on your needs and output cap
OUTPUT_TOKENS=4000    # Lower to use fewer output tokens
INPUT_TOKENS=60000    # Adjust based on conversation length
```

### Model Selection
- **Ollama Cloud**: `deepseek-v4.1-flash:1017` is the shipped default.
- **OpenAI**: any model the account can use; choose a reasoning model when the task needs it.
- **Local Ollama**: choose an installed model and match `CONTEXT_WINDOW` to its limits.

### Parameter support
- `max_tokens` caps visible output plus reasoning tokens on Ollama-compatible hosts;
  `max_completion_tokens` does the same on every other OpenAI-compatible host, not only
  `api.openai.com`.
- `reasoning_effort` is sent from `REASONING_EFFORT` only when non-empty; valid values are
  model-defined.
- `verbosity` and sampling overrides are not sent. Function tools are offered only on Ollama-compatible hosts when `WEB_TOOLS` is true.

## Monitoring & Debugging

The console format is `<iso timestamp> [level    ] <event> [<logger>] [field=value ...]`;
`channel_id`, `guild_id`, and `user_id` follow the logger when the message logger supplied
them. Grep for the event text. Module loggers render as `[src.<module>]`; the top-level bot
logger is `[discordianai.bot]`. The provider request and routing lines below use that bot
logger because the request supplies it.

### Response Logs
```
2026-11-23T17:04:06Z [info     ] OpenAI response generated successfully: 245 characters, finish_reason: stop [discordianai.bot] channel_id=123456789012345678
2026-11-23T17:04:06Z [warning  ] OpenAI returned empty response content (finish_reason=length) [discordianai.bot] channel_id=123456789012345678
```

### Service Selection Logs
```
2026-11-23T17:04:06Z [info     ] Routing decision: {'route': 'local', 'service': 'openai', ...} [discordianai.bot] channel_id=123456789012345678
2026-11-23T17:04:06Z [info     ] Routing to OpenAI [discordianai.bot] channel_id=123456789012345678
```

### Error Logs
```
2026-11-23T17:04:06Z [error    ] OpenAI API call failed after retries [discordianai.bot]
2026-11-23T17:04:06Z [info     ] OpenAI returned no response; attempting Perplexity fallback [discordianai.bot]
```

## Usage Optimization Tips

### Smart Usage
1. **Use the default model** for simple queries to use fewer tokens
2. **Set appropriate OUTPUT_TOKENS** limit based on your needs
3. **Monitor token usage** in the provider's own console if needed; the bot does not log usage
4. **Account for reasoning tokens** in the output cap; they count toward it

### Rate Limiting
```ini
[Limits]
RATE_LIMIT=10          # Messages per time period
RATE_LIMIT_PER=60      # Time period in seconds
```

### Conversation History Management
```ini
[Orchestrator]
MAX_HISTORY_PER_USER=30  # Reduce to save tokens on context
```

## Troubleshooting

### Common Issues

**"No API key provided"**:
- Ensure `OPENAI_API_KEY` is set in config.ini or environment variables
- A non-`sk-` key is accepted for non-OpenAI providers; a warning notes the shape mismatch

**"Rate limit exceeded"**:
- Check the provider's usage limits
- Implement appropriate rate limiting in bot configuration

**"Model not found"**:
- Verify the model name with the configured provider
- Check that the account has access to the specified model

**High usage**:
- Lower `OUTPUT_TOKENS` setting
- Use a smaller or non-reasoning model when the task allows
- Reduce `MAX_HISTORY_PER_USER` to minimize context tokens

### Getting Help
- Check the configured provider's API documentation
- Monitor the bot logs for specific error messages
- Review the provider's usage records
