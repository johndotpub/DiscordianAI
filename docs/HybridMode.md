# Smart AI Mode: Advanced GPT-5 + Perplexity Integration

## Overview

DiscordianAI features a sophisticated AI orchestration system with intelligent routing, conversation consistency, and three flexible operation modes:

1. **OpenAI Only** - Use GPT-5 for all responses
2. **Perplexity Only** - Use Sonar-Pro with web search for all responses  
3. **Smart Hybrid** - Automatically choose the best AI for each message with conversation consistency

## AI Service Consistency System 🔄

DiscordianAI reuses the previous AI service only for genuine anaphora within the
same conversation. A follow-up pattern must match, and a recent assistant turn
must exist in that conversation's history; the router then reuses that turn's
service. A matched follow-up with no recent assistant turn is routed to OpenAI
rather than being treated as a web-search query.

### How It Works

1. **Metadata Tracking**: Every AI response records the service and model that generated it
2. **Conversation Scope**: History is keyed per DM user or per guild channel/thread, so another channel or user cannot supply the previous service
3. **Follow-up Detection**: Only genuine anaphora match: whole-message continuations (bare "more", "continue", "go on", or "keep going"), "tell/show/give me more", "what/how about", ordinal references such as "the second one", whole-message "and then", "then what", or "what now", a bare pronoun ("it", "that", "they", ...), or a bare "yes", "no", "ok", or "okay"
4. **Consistent Routing**: If the lookback window contains a recent assistant turn, the router reuses its service; otherwise the message falls through to the normal routing heuristics

A word such as "also" or "more" inside a fresh question does not turn that
question into a follow-up.

### Example Flow
```
User: "What's the weather in Tokyo today?"
→ 🌐 Routed to Perplexity (time-sensitive, current data needed)
→ Response: "Tokyo is currently 22°C with light rain..." + metadata

User: "Tell me more"
→ 🔄 Detected as anaphora in the same conversation, checks recent AI service used
→ 🌐 Routed to Perplexity for consistency
→ User gets a detailed forecast from the same service with full context
```

## Message Flow Architecture

The following diagram shows how messages flow through the DiscordianAI system:

```mermaid
flowchart TD
    A[Discord Message Received] --> B{Bot Mentioned?}
    B -->|No| Z[Ignore Message]
    B -->|Yes| C[Rate Limit + Guardrails]
    C -->|Failed| D[Send Rate Limit Message]
    C -->|Passed| E[Smart Orchestrator Analysis]

    E --> L[Model Guard\n(GPT-5 + Sonar-Pro)]
    L --> F{Mode Selector}

    F -->|OpenAI Only| G[OpenAI Processing\n(GPT-5 family)]
    F -->|Perplexity Only| H[Perplexity Processing\n(Sonar models)]
    F -->|Hybrid| I[Check Conversation Context]

    I --> J{Follow-up Detected?}
    J -->|Yes| K[Reuse Previous AI Service]
    J -->|No| M[Analyze Message Content]

    M --> SR[Sanitize for routing]
    SR --> SI{Search Intent?}
    SI -->|Yes| H
    SI -->|No| N{URLs Detected?}
    N -->|Yes| H
    N -->|No| O{Time-sensitive or Entities?}
    O -->|Yes| H
    O -->|No| P{Conversational/Creative?}
    P -->|Yes| G
    P -->|No| Q{Factual Query?}
    Q -->|Yes| H
    Q -->|No| G

    K --> T{Previous Service}
    T -->|OpenAI| G
    T -->|Perplexity| H

    G --> R[GPT-5 Response Payload]
    H --> PR[Sonar-Pro Response + Citations]

    %% OpenAI response path includes in-line web-inability detection and fallback
    R --> OW[OpenAI Response]
    OW --> WI{Indicates web-inability?}
    WI -->|Yes| H
    WI -->|No| U[Message Processor Formatting]

    PR --> V[Citation Embed Formatter]

    U --> W[send_formatted_message]
    V --> W

    W --> X{Contains Embeds?}
    X -->|Yes| Y{Embed > Limits?}
    X -->|No| Z1{Message > 2000 chars?}

    Y --> CC[Split Embed + Citations]
    Z1 --> DD[Split Plain Message]
    CC --> BB[✅ Response Complete]
    DD --> BB
```

### Key Anti-Duplication Features

The diagram above shows the **critical control flow fix** that prevents duplicate messages:

1. **Single Entry Point**: All responses go through `send_formatted_message` 
2. **Explicit Returns**: Each successful send has a `return` statement to exit the function
3. **Embed Priority**: Perplexity responses with citations try embed first, fallback to regular message only on failure
4. **No Fallthrough**: Fixed the bug where embed success still continued to regular message logic

This ensures **exactly one message** is sent per user query, eliminating the duplicate message issue.

### Model Guardrails

- `api_validation.validate_openai_config()` warns when `GPT_MODEL` falls outside the documented GPT-5 identifiers; unknown names do not block startup.
- Perplexity calls only expose `model` and `max_tokens`; Sonar-Pro is the default and sampling is handled by the API.
- Temperature toggles were removed because GPT-5 and Sonar-Pro ignore external sampling overrides.

## Smart Detection (No Manual Triggers Required!)

The bot uses advanced semantic analysis to automatically determine when web search would be beneficial:

### Smart Detection Criteria

**Uses Web Search When:**
- Time-sensitive questions ("today", "recently", "latest")
- Factual queries about changeable information (weather, stocks, news)
- Questions about specific companies, people, or current events
- Longer, detailed questions that suggest need for current data

**Uses Regular AI When:**
- Creative requests (stories, poems, jokes)
- Technical/coding help
- Philosophical discussions
- Personal conversations and greetings
- General knowledge that doesn't change

### Example Auto-Detection

**Automatically Uses Perplexity:**
- "What's happening in AI today?" ← Time-sensitive
- "How's Tesla's stock doing?" ← Financial data
- "What's the weather like?" ← Current information
- "Tell me about the recent SpaceX launch" ← Current events

**Automatically Uses GPT-5:**
- "Write me a poem about robots" ← Creative
- "How do I fix this Python error?" ← Technical
- "What do you think about philosophy?" ← Opinion/conversation
- "Hello! How are you?" ← Greeting

## Discord Citation Features

### Citations
- Message text keeps bare numbered markers such as `[1]` and `[2]`. Production calls the formatter with `linkify=False`, so the message body does not contain clickable citation links.
- Clickable citations exist only in the citation embed, where a marker renders as `[[1]](https://full-url)`.
- A citation URL is left intact only when it is allowlisted and safely renderable; other links are neutralised by the output sanitiser.

### Smart Embed Suppression
- Automatically suppresses link previews when there are multiple citations
- Prevents chat from being cluttered with preview images
- Keeps messages readable and focused

## Configuration Modes

### Mode 1: Smart Hybrid (Recommended)
Uses both APIs and automatically chooses the best one:

```ini
# Both APIs configured
OPENAI_API_KEY=your_openai_api_key_here
PERPLEXITY_API_KEY=your_perplexity_api_key_here
```

### Mode 2: OpenAI Only
Uses only GPT-5 for all responses:

```ini
# Only OpenAI configured
OPENAI_API_KEY=your_openai_api_key_here
PERPLEXITY_API_KEY=
```

### Mode 3: Perplexity Only
Uses only Perplexity with web search for all responses:

```ini
# Only Perplexity configured  
OPENAI_API_KEY=
PERPLEXITY_API_KEY=your_perplexity_api_key_here
```

## Advanced Configuration: AI Orchestrator Settings ⚙️

Fine-tune the AI service selection behavior with these advanced configuration options in your `config.ini`:

```ini
[Orchestrator]
# AI Orchestrator Configuration for advanced routing and optimization
# How many recent messages to check for AI service consistency
LOOKBACK_MESSAGES_FOR_CONSISTENCY=6

# Maximum conversation entries per user before pruning
MAX_HISTORY_PER_USER=50

# How often to clean up inactive user locks (seconds) - default 1 hour
USER_LOCK_CLEANUP_INTERVAL=3600
```

### Configuration Explained

| Setting | Default | Description |
|---------|---------|-------------|
| `LOOKBACK_MESSAGES_FOR_CONSISTENCY` | 6 | How many recent messages to check when determining AI service consistency for follow-ups |
| `MAX_HISTORY_PER_USER` | 50 | Maximum conversation entries stored per user (older entries are automatically pruned) |
| `USER_LOCK_CLEANUP_INTERVAL` | 3600 | How often to clean up memory from inactive users (in seconds) |

`ENTITY_DETECTION_MIN_WORDS=10` is parsed into config and available for routing; messages shorter than the threshold can be excluded from entity-heavy processing. Note: this setting is not yet wired into the current routing implementation and has no runtime effect.

### Performance Impact
- **Higher `LOOKBACK_MESSAGES_FOR_CONSISTENCY`**: More accurate consistency but slightly more processing
- **Higher `MAX_HISTORY_PER_USER`**: Better long-term context but more memory usage
- **Lower `USER_LOCK_CLEANUP_INTERVAL`**: More frequent memory cleanup but slight CPU overhead

## Setup Instructions

### 1. Get API Keys (as needed)

**OpenAI API Key** (for GPT-5):
- Go to https://platform.openai.com/api-keys
- Create a new API key

**Perplexity API Key** (for web search):
- Go to https://www.perplexity.ai/settings/api
- Generate an API key

### 2. Choose Your Configuration

Copy `config.ini.example` to `config.ini` and toggle the keys for your desired mode:
- **Hybrid**: Provide both `OPENAI_API_KEY` and `PERPLEXITY_API_KEY`.
- **OpenAI Only**: Set `PERPLEXITY_API_KEY` blank.
- **Perplexity Only**: Set `OPENAI_API_KEY` blank.

Environment variables with the same names override `config.ini`, so production deployments can keep secrets out of the file system.

### 3. Test It

Start your bot and try these examples:

- "Hello!" ← Uses GPT-5
- "What's the latest AI news?" ← Uses Perplexity
- "Tell me about today's weather" ← Uses Perplexity
- "How do I learn Python?" ← Uses GPT-5

## Fallback Behavior

The hybrid orchestrator (`smart_orchestrator.py`) provides bidirectional fallback between services:

- **OpenAI failure → Perplexity**: When OpenAI returns no response (quota exhaustion, auth errors, timeouts), the orchestrator automatically retries with Perplexity for web-enabled fallback.
- **Perplexity failure → OpenAI**: When Perplexity fails (network errors, timeouts), the orchestrator falls back to OpenAI for standard completion.
- **Web-inability reroute**: If OpenAI responds but indicates it cannot browse the web (e.g., "I can't browse the internet"), the orchestrator detects this and reroutes to Perplexity.
- **Both unavailable**: Returns the `both_services_unavailable` message
  (`"🔧 All AI services are temporarily unavailable. Please try again later."`).

Both services share identical retry policy via `retry_with_backoff`:
- 2 attempts max (1 initial + 1 retry) for transient errors (network/connection errors, connect timeouts, 429, 5xx)
- `insufficient_quota`, authentication errors, and read timeouts bail immediately — no wasted retries
- The single retry waits a random 0–1s (full jitter over the base delay); a 429 can instead honour `Retry-After` up to 30s
- A 90s `max_elapsed` deadline stops retries even when an attempt remains
- SDK-level `max_retries=0` prevents nested retry multiplication

## Cost Considerations

- **GPT-5**: Higher cost per token but excellent reasoning
- **Perplexity**: Lower cost for web search, includes citations
- The bot automatically chooses the most cost-effective option based on the query type

## Monitoring & Debugging 🔍

Check your logs to see the AI orchestration system in action:

### AI Service Selection Logs
```
INFO: Smart orchestrator processing message from user 123456789: What's the weather...
INFO: Running in hybrid mode - analyzing message for optimal routing
INFO: Message analysis suggests web search would be beneficial - trying Perplexity first
INFO: Perplexity response generated successfully (245 chars)
```

### Consistency System Logs  
```
INFO: Smart orchestrator processing message from user 123456789: Tell me more
INFO: Running in hybrid mode - analyzing message for optimal routing
DEBUG: Follow-up detected, using recent AI service: perplexity
INFO: Message analysis suggests web search would be beneficial - trying Perplexity first
INFO: Perplexity response successful in hybrid mode (312 chars)
```

### Conversation Management
```
DEBUG: Retrieved conversation for user 123456789: 8 messages
DEBUG: Generated conversation summary for user 123456789: 6 messages
INFO: Added assistant message for user 123456789: 245 chars, total history: 9 messages
```

### Performance Monitoring
```
INFO: Cleaned up 3 inactive user locks for memory optimization
DEBUG: Rate limit check successful for User123 (ID: 123456789)
```

## Thread-Safe Architecture 🔒

DiscordianAI uses a robust thread-safe architecture that handles concurrent users safely:

### Features
- **Per-User Locking**: Each user has their own conversation lock to prevent race conditions
- **Thread-Safe Conversation Management**: All conversation operations are atomic and thread-safe  
- **Memory Management**: Automatic cleanup of inactive user locks to prevent memory leaks
- **Metadata Tracking**: AI service information stored with each message for consistency

### Benefits
- **Concurrent Users**: Multiple users can chat simultaneously without data corruption
- **Consistent State**: Conversation state remains consistent even under high load
- **Memory Efficiency**: Automatic cleanup prevents memory bloat in long-running deployments
- **Production Ready**: Designed for high-availability production environments

## Customization & Advanced Usage 🛠️

### Detection Pattern Customization
Adjust the AI service selection patterns in `src/config.py`:

```python
# Time-sensitive patterns (raw patterns from config.py; one representative entry)
TIME_SENSITIVITY_PATTERNS = [
    r"\b(today|yesterday|this week|this month|this year|recently|latest|current)\b",
]

# Follow-up detection patterns (raw patterns from config.py)
FOLLOW_UP_PATTERNS = [
    r"^\s*(more|continue|go on|keep going)(\s+please)?\s*[.!?]*\s*$",
    r"^\s*(tell|show|give)\s+me\s+more\s*[.!?]*\s*$",
    r"\b(what|how)\s+about\b",
    r"\b(and|what about|how about)\s+(the\s+)?(first|second|third|last|next|other)\s+one\b",
    r"^\s*(and|so|but)?\s*(the\s+)?(first|second|third|last|next|other)\s+one\s*[.!?]*\s*$",
    r"^\s*(it|that|this|those|these|they|them|he|she|him|her)\s*[.!?]*\s*$",
    r"^\s*(yes|no|ok|okay)\s*[.!?]*\s*$",
    r"^\s*(and then|then what|what now)\s*\??\s*$",
]
```

### Environment Variable Override
All configuration values can be overridden via environment variables:

```bash
export LOOKBACK_MESSAGES_FOR_CONSISTENCY=8
export MAX_HISTORY_PER_USER=100
```

### Production Deployment Tips
1. **Monitor Memory**: Watch the logs for cleanup messages to ensure memory management is working
2. **Adjust History**: Increase `MAX_HISTORY_PER_USER` for better long-term context
3. **Tune Consistency**: Adjust `LOOKBACK_MESSAGES_FOR_CONSISTENCY` based on your user conversation patterns
