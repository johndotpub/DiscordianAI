# Perplexity Integration Guide

DiscordianAI provides comprehensive Perplexity integration for real-time web search capabilities with intelligent citation formatting and embed suppression for optimal Discord experience.

## Supported Models

### Sonar-Pro (Recommended)
- **Latest web search model** with enhanced accuracy
- **Real-time information access** from current web sources
- **Advanced citation extraction** with URL formatting
- **Optimized for recent events** and factual queries

### Sonar (General)
- **Standard web search model** for general queries
- **Reliable information retrieval** from web sources
- **Good citation support** with source attribution
- **Cost-effective option** for basic web search needs

## Configuration

### Basic Perplexity Setup
```ini
[Default]
# Perplexity API configuration
PERPLEXITY_API_KEY=your_perplexity_api_key_here
PERPLEXITY_API_URL=https://api.perplexity.ai
PERPLEXITY_MODEL=sonar-pro

# Response settings
OUTPUT_TOKENS=8000
TEMPERATURE=0.7  # Good for web search synthesis

# System message for web search
SYSTEM_MESSAGE=You are a helpful assistant with access to current web information. When providing citations, include source URLs when available.
```

## Operation Modes

### Perplexity Only Mode
Disable OpenAI to use only web search:
```ini
OPENAI_API_KEY=
PERPLEXITY_API_KEY=your_perplexity_key_here
```

### Hybrid Mode (Smart Routing)
Enable both for intelligent routing:
```ini
OPENAI_API_KEY=your_openai_key_here
PERPLEXITY_API_KEY=your_perplexity_key_here
```

## Key Features

### 🌐 Real-Time Web Search
- Access to current information and breaking news
- Real-time data from various web sources
- Up-to-date facts and statistics

### 📚 Citation Management
- Automatic citation extraction from responses
- **Discord embed formatting** for clickable citation hyperlinks
- Source attribution with proper `[[1]](url)` formatting
- **Smart embed creation** only when citations are present

### 🎯 Smart Embed Suppression
- Automatically suppresses Discord embeds when 2+ links present
- Prevents channel clutter from multiple link previews
- Maintains clean conversation flow

### 🧠 Intelligent Query Routing
The bot automatically uses Perplexity for:
- Current events and news queries
- Time-sensitive information requests
- Factual research questions
- Queries with proper nouns and entities

## Citation Format

Perplexity responses include properly formatted citations that are automatically converted to clickable Discord hyperlinks:

```
The latest developments in AI research show significant progress [1]. 
Companies are investing heavily in machine learning capabilities [2].

**Sources:**
[1] https://example.com/ai-research-2024
[2] https://example.com/ml-investments
```

### Discord Integration
- **Clickable Citations**: Numbers like [1], [2] become clickable hyperlinks
- **Preserved Format**: Citation numbers remain visible for readability
- **Smart Embed Suppression**: Prevents link preview clutter with multiple citations
- **Clean Appearance**: Maintains clean, readable message format

## Configuration Examples

### Web Search Focused Bot
```ini
[Default]
PERPLEXITY_API_KEY=pplx-your-key-here
PERPLEXITY_MODEL=sonar-pro
OUTPUT_TOKENS=8000

# Optimize for web search
SYSTEM_MESSAGE=You are a research assistant with access to real-time web information. Always provide sources for factual claims.
```

### Balanced Hybrid Setup
```ini
[Default]
OPENAI_API_KEY=sk-your-openai-key
PERPLEXITY_API_KEY=pplx-your-perplexity-key

# Smart routing configuration
[Orchestrator]
LOOKBACK_MESSAGES_FOR_CONSISTENCY=6
ENTITY_DETECTION_MIN_WORDS=10
```

## Orchestrator Integration

### Smart Query Analysis
The bot analyzes queries to determine when web search is beneficial:

- **Time sensitivity patterns**: "latest", "current", "recent", "today"
- **Factual query indicators**: "what is", "how many", "statistics"
- **Entity detection**: Company names, locations, people, events
- **Follow-up consistency**: Maintains same AI service for related queries

### Routing Decision Logic
1. **Conversation context**: Checks recent AI service usage
2. **Conversational queries**: Routes creative/personal queries to OpenAI
3. **Current events**: Routes time-sensitive queries to Perplexity
4. **Factual research**: Routes fact-finding queries to Perplexity
5. **Entity-rich queries**: Routes specific searches to Perplexity

## Best Practices

### Query Optimization
- **Be specific**: Include relevant keywords and context
- **Use current terms**: Include dates, locations, or recent terminology
- **Ask follow-ups**: The bot maintains conversation context

### Model Selection
- Use **sonar-pro** for latest information and breaking news
- Use **sonar** for general web search and research queries
- Consider token costs when setting OUTPUT_TOKENS

### Integration Tips
- **Hybrid mode recommended**: Combines web search with conversational AI
- **Set appropriate context**: Use ENTITY_DETECTION_MIN_WORDS for precision
- **Monitor usage**: Track API costs and optimize token limits

## Troubleshooting

### Common Issues

**"No API key provided"**:
- Ensure `PERPLEXITY_API_KEY` is set in config.ini or environment variables
- Verify the API key starts with `pplx-`

**"Rate limit exceeded"**:
- Check your Perplexity billing and usage limits
- Implement appropriate rate limiting in bot configuration

**"Model not found"**:
- Verify the model name is correct (supported: `sonar-pro`, `sonar`)
- Check if you have access to the specified model

**Citations not formatting properly**:
- Ensure OUTPUT_TOKENS is sufficient (recommended: 8000+)
- Check that citation extraction patterns are working
- Verify Discord message length limits aren't truncating citations

**Too many embeds in Discord**:
- The bot automatically suppresses embeds when 2+ links are present
- This prevents channel clutter from multiple link previews
- Citations are still fully accessible as clickable text

### Performance Optimization

- **Adjust OUTPUT_TOKENS**: Higher values allow for more complete responses with citations
- **Use temperature 0.7**: Optimal for factual synthesis while maintaining readability
- **Monitor API costs**: Track usage patterns and optimize for your use case

## Environment Variables

For production deployment, use environment variables:

```bash
export PERPLEXITY_API_KEY="pplx-your-key-here"
export PERPLEXITY_API_URL="https://api.perplexity.ai"
export PERPLEXITY_MODEL="sonar-pro"
```

## Getting Help

- Check Perplexity's [API documentation](https://docs.perplexity.ai/)
- Monitor the bot logs for specific error messages
- Verify your API key has sufficient credits and permissions
- Test with simple queries first to ensure connectivity

## Advanced Features

### Context-Aware Search
- The bot maintains conversation context across queries
- Follow-up questions automatically use the same AI service
- Conversation summary helps provide relevant context to searches

### Metadata Tracking
- All Perplexity responses include service metadata
- Citation counts are tracked for analytics
- API usage is logged for monitoring and optimization

### Error Handling
- Graceful fallback to OpenAI when Perplexity is unavailable
- Retry logic with exponential backoff for transient failures
- Circuit breaker pattern prevents cascade failures
