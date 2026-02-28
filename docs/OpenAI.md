# OpenAI Integration Guide

DiscordianAI provides comprehensive OpenAI integration with support for GPT-5 series models, including advanced features like conversation consistency and metadata tracking.

## Supported Models

### GPT-5 Series
- **GPT-5**: High-quality reasoning and complex tasks
- **GPT-5-mini**: Cost-effective option for general use
- **GPT-5-nano**: High-speed processing with low latency
- **GPT-5-chat**: Advanced conversational interactions

## Configuration

### Basic OpenAI Setup
```ini
[Default]
# OpenAI API configuration
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_API_URL=https://api.openai.com/v1/
GPT_MODEL=gpt-5-mini

# Token limits
OUTPUT_TOKENS=8000
INPUT_TOKENS=120000
CONTEXT_WINDOW=128000

# System message for personality
SYSTEM_MESSAGE=You are a helpful AI assistant with access to current information.
```

### GPT-5 Notes
OpenAI models use the standard Chat Completions API parameters. Only officially supported parameters are used (e.g., `model`, `messages`, `max_completion_tokens`). GPT-5 frontier models enforce their own sampling so temperature overrides are ignored.

## Operation Modes

### OpenAI Only Mode
Disable Perplexity to use only OpenAI:
```ini
OPENAI_API_KEY=your_openai_api_key_here
PERPLEXITY_API_KEY=
```

### Smart Hybrid Mode  
Enable both for intelligent routing:
```ini
OPENAI_API_KEY=your_openai_api_key_here
PERPLEXITY_API_KEY=your_perplexity_key_here
```

## Advanced Features

### Conversation Consistency
- **Metadata Tracking**: Each OpenAI response includes model and service information
- **Follow-up Routing**: Follow-up questions automatically route to OpenAI if the previous response came from OpenAI
- **Context Preservation**: Maintains conversation context across multiple exchanges

### Thread-Safe Architecture
- **Per-User Conversations**: Each user has isolated conversation history
- **Concurrent Processing**: Multiple users can chat simultaneously without interference
- **Memory Management**: Automatic cleanup of old conversation data

### Error Handling & Fallbacks
- **Graceful Degradation**: If OpenAI fails, system provides helpful error messages
- **Retry Logic**: Automatic retries for transient API failures
- **Logging**: Comprehensive logging for debugging and monitoring

## Usage Examples

### Conversational Queries (Auto-routed to OpenAI)
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
# Adjust based on your needs and budget
OUTPUT_TOKENS=4000    # Lower for cost savings
INPUT_TOKENS=60000    # Adjust based on conversation length
```

### Model Selection
- **GPT-5**: Best quality, highest cost - for complex reasoning tasks
- **GPT-5-mini**: Cost-effective default - best balance of quality and cost
- **GPT-5-nano**: High-speed processing - for low-latency responses
- **GPT-5-chat**: Advanced conversational interactions

### Parameter support
- This project does not use unofficial parameters. There is no `reasoning_effort` or `verbosity`.

## Monitoring & Debugging

### Token Usage Logs
```
INFO: Token usage - Prompt: 1250, Completion: 450, Total: 1700
INFO: OpenAI response generated successfully: 245 characters
```

### Service Selection Logs
```
INFO: Message analysis suggests conversational AI is optimal - using OpenAI
INFO: OpenAI response successful in hybrid mode (312 chars)
```

### Error Logs
```
ERROR: OpenAI API call failed for user 123456789: Rate limit exceeded
WARNING: OpenAI returned no response, trying fallback
```

## Cost Optimization Tips

### Smart Usage
1. **Use GPT-5-mini** for simple queries to reduce costs (default)
2. **Set appropriate OUTPUT_TOKENS** limit based on your needs
3. **Monitor token usage** in logs to track spending
4. Keep `max_tokens` conservative for cost control

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
- Verify the API key starts with `sk-`

**"Rate limit exceeded"**:
- Check your OpenAI billing and usage limits
- Implement appropriate rate limiting in bot configuration

**"Model not found"**:
- Verify the model name is correct (examples: `gpt-5-mini`, `gpt-5`, `gpt-5-nano`, `gpt-5-chat`)
- Check if you have access to the specified model

**High costs**:
- Lower `OUTPUT_TOKENS` setting
- Use `gpt-5-mini` for cost-effective responses (default)
- Use `gpt-5` for enhanced capabilities when needed
- Reduce `MAX_HISTORY_PER_USER` to minimize context tokens

### Getting Help
- Check OpenAI's [API documentation](https://platform.openai.com/docs)
- Monitor the bot logs for specific error messages
- Review your OpenAI usage dashboard for billing information
