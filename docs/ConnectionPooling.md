# Connection Pooling Configuration

DiscordianAI uses optimized HTTP connection pooling to maximize performance while respecting API rate limits. This document explains the configuration options and their rationale.

## Overview

The bot uses separate connection pools for OpenAI and Perplexity APIs, each tuned for their specific characteristics and rate limits. This allows efficient handling of multiple concurrent users without overwhelming the APIs.

## Configuration Options

### OpenAI Connection Pool

```ini
[ConnectionPool]
# OpenAI typically handles more concurrent requests
OPENAI_MAX_CONNECTIONS=50
OPENAI_MAX_KEEPALIVE=10
```

**Rationale:**
- **50 max connections**: Allows handling ~500 requests per minute (OpenAI's rate limit)
- **10 keepalive**: Maintains persistent connections for frequently used clients
- **Higher capacity**: OpenAI's infrastructure can handle more concurrent connections

### Perplexity Connection Pool

```ini
[ConnectionPool]
# Perplexity has more conservative limits
PERPLEXITY_MAX_CONNECTIONS=30
PERPLEXITY_MAX_KEEPALIVE=5
```

**Rationale:**
- **30 max connections**: Conservative limit for Perplexity's web search API
- **5 keepalive**: Lower keepalive count due to less frequent usage patterns
- **Web search focus**: Perplexity is typically used for time-sensitive queries

## API Rate Limits

### OpenAI API Limits
- **Requests per minute**: 500 RPM (varies by model and account tier)
- **Tokens per minute**: 200,000 TPM for gpt-3.5-turbo, 10,000 TPM for gpt-4
- **Connection limits**: No explicit connection limits, but rate limits apply

### Perplexity API Limits
- **Rate limits**: Not publicly documented (contact Perplexity support for details)
- **Connection limits**: Conservative approach recommended
- **Usage patterns**: Typically used for web search queries

## Performance Benefits

### Connection Reuse
- **Shared pools**: Multiple users share the same HTTP connections
- **Reduced overhead**: No need for 1:1 user-to-connection mapping
- **HTTP/2 multiplexing**: Multiple requests over single connections

### Memory Efficiency
- **10k users**: ~100MB total conversation memory
- **Connection overhead**: Minimal with shared pools
- **Scalable**: Supports large user bases efficiently

## Monitoring and Tuning

### Key Metrics to Monitor
- **Connection pool utilization**: Should stay well below max connections
- **Rate limit errors**: 429 responses indicate hitting API limits
- **Response times**: Should remain consistent under load

### Tuning Guidelines
- **Increase connections**: If you see connection pool exhaustion
- **Decrease connections**: If you hit rate limits frequently
- **Monitor usage**: Use API dashboards to track actual usage patterns

## Default Settings

The default configuration is designed for:
- **Small to medium deployments**: 10-100 concurrent users
- **Mixed usage patterns**: Both conversational and web search queries
- **Rate limit compliance**: Stays well within API limits

For larger deployments, consider:
- Increasing connection limits gradually
- Monitoring API usage dashboards
- Contacting API providers for higher rate limits

## Troubleshooting

### Common Issues
1. **Rate limit errors (429)**: Reduce connection limits or implement backoff
2. **Connection timeouts**: Check network connectivity and increase timeouts
3. **Memory usage**: Monitor conversation history limits

### Debug Configuration
Enable debug logging to see connection pool metrics:
```ini
[Logging]
LOG_LEVEL=DEBUG
```

This will show connection pool creation and usage statistics in the logs.

## HTTP/2 Support

### Automatic HTTP/2 Detection
The connection pool automatically enables HTTP/2 when available:
- **HTTP/2 Enabled**: Uses multiplexed connections for better performance
- **Graceful Fallback**: Falls back to HTTP/1.1 if `h2` package is missing
- **Logging**: Shows HTTP/2 status in logs for monitoring

### Requirements
To enable HTTP/2 support, install the full httpx package:
```bash
pip install httpx[http2]>=0.28.0 h2>=4.3.0
```

**Note**: HTTP/2 support requires httpx 0.28.0+ for reliable operation. Earlier versions may fall back to HTTP/1.1.

### Troubleshooting HTTP/2
If you see "HTTP/2 not available" warnings:
1. Install HTTP/2 dependencies: `pip install httpx[http2]>=0.28.0 h2>=4.3.0`
2. Restart the bot to enable HTTP/2
3. Check logs for "HTTP/2 enabled" confirmation

**Common Issues:**
- **httpx < 0.28.0**: HTTP/2 support is unreliable, upgrade to 0.28.0+
- **Missing h2 package**: Install with `pip install h2>=4.3.0`
- **Version conflicts**: Use `pip install --force-reinstall httpx[http2]>=0.28.0 h2>=4.3.0`