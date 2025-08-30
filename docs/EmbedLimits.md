# Discord Embed Limits Configuration

This document explains DiscordianAI's Discord embed limit constants and their usage.

## Configuration Constants

Located in `src/config.py`:

```python
# Discord Message Constants
MESSAGE_LIMIT = 2000        # Discord's hard limit for regular messages
EMBED_LIMIT = 4096          # Discord's hard limit for embed descriptions
EMBED_SAFE_LIMIT = 3840     # Safe margin for citation expansion and formatting
MAX_SPLIT_RECURSION = 10    # Safety limit for message splitting recursion
```

## Why Two Embed Limits?

### Hard Limit (`EMBED_LIMIT` = 4096)
- **Purpose**: Discord's absolute maximum for embed descriptions
- **Usage**: Validation and overflow detection
- **When**: Checking if content needs splitting across multiple embeds

### Safe Limit (`EMBED_SAFE_LIMIT` = 3840)
- **Purpose**: Practical limit with safety buffer
- **Usage**: Content truncation and split point calculation  
- **Buffer**: 256 characters (6.25% safety margin)

## Safety Buffer Breakdown

The 256-character buffer accommodates:

| Component | Example | Expansion |
|-----------|---------|-----------|
| Citation formatting | `[1]` → `[[1]](https://example.com/long/url)` | 3 → 50+ chars |
| Footer text | `📚 5 sources` | ~15 chars |
| Continuation markers | `(continued)` | ~12 chars |
| Unicode encoding | Emoji, special chars | Variable |
| **Total Buffer** | | **256 chars** |

## Real-World Example

```python
# Original content with citations
content = "This is research about AI [1] and machine learning [2]..."

# After citation formatting
formatted = "This is research about AI [[1]](https://academic-journal.com/ai-research-paper-2024) and machine learning [[2]](https://university.edu/ml-study)..."

# Content expansion: ~3x longer due to citation URLs
```

## Usage in Code

### Truncation Logic
```python
# discord_embeds.py
if len(formatted_content) > EMBED_LIMIT:
    formatted_content = formatted_content[:EMBED_SAFE_LIMIT] + "..."
```

### Split Point Calculation
```python
# bot.py
if len(message) > EMBED_SAFE_LIMIT:
    split_point = find_optimal_split_point(message, EMBED_SAFE_LIMIT)
```

### Overflow Detection
```python
# bot.py
was_truncated = (
    len(clean_text) > EMBED_LIMIT 
    and embed_description.endswith("...")
)
```

## Benefits

✅ **Prevents Discord API Errors**: Never exceed hard limits  
✅ **Preserves Citation Functionality**: URLs don't break formatting  
✅ **Maintains Readability**: Clean truncation with proper indicators  
✅ **Future-Proof**: Buffer handles format changes  
✅ **Performance**: Avoids retry logic from failed sends  

## Configuration Guidelines

1. **Don't change EMBED_LIMIT** - This is Discord's API limit
2. **Adjust EMBED_SAFE_LIMIT** if needed based on:
   - Average citation URL length in your use case
   - Footer text requirements
   - Performance vs safety trade-offs

## Monitoring

Watch for these log messages:
```
Embed description truncated from 4200 to EMBED_LIMIT chars
Embed content was truncated (4500 chars), splitting message
```

These indicate the limits are working correctly to prevent API errors.
