# Message Splitting & Character Limits

DiscordianAI implements intelligent message splitting to handle Discord's character limits while preserving formatting, code blocks, and citation functionality.

## Discord Character Limits

### Regular Messages
- **Limit**: 2000 characters
- **Usage**: OpenAI responses, plain text
- **Splitting**: Intelligent boundary detection

### Embed Descriptions  
- **Limit**: 4096 characters
- **Usage**: Perplexity responses with citations
- **Splitting**: Citation-aware splitting

## Message Splitting Algorithm

The following diagram shows how messages are intelligently split:

```mermaid
flowchart TD
    A[Message Content] --> B{Content Type?}
    
    B -->|Regular Text| C{Length > 2000?}
    B -->|Embed Content| D{Length > 4096?}
    
    C -->|No| E[Send Single Message]
    C -->|Yes| F[Find Optimal Split Point]
    
    D -->|No| G[Send Single Embed]
    D -->|Yes| H[Find Embed Split Point]
    
    F --> I[Check for Code Blocks]
    H --> J[Check Citation Distribution]
    
    I --> K{Inside Code Block?}
    K -->|Yes| L[Adjust Split to Preserve Code]
    K -->|No| M[Split at Natural Boundary]
    
    J --> N[Map Citations to Parts]
    N --> O[Create Multiple Embeds]
    O --> P{More Content?}
    P -->|Yes| Q[Create Continuation Embed]
    P -->|No| R[Complete]
    
    L --> S[Send First Part]
    M --> S
    S --> T[Send Remaining Parts]
    
    G --> U[Response Complete]
    E --> U
    T --> U
    R --> U
    Q --> V[Send All Embed Parts]
    V --> U
```

## Split Point Detection

### Priority Order
1. **Newline boundaries** - Preserve paragraph structure
2. **Sentence endings** - Maintain readability (. ! ?)
3. **Word boundaries** - Avoid cutting words in half
4. **Character limit** - Fallback when no good boundaries exist

### Code Block Preservation

```mermaid
flowchart TD
    A[Split Point Found] --> B{Inside Code Block?}
    B -->|No| C[Use Split Point]
    B -->|Yes| D[Find Code Block Boundaries]
    
    D --> E{Can Fit Entire Block?}
    E -->|Yes| F[Move Split After Block]
    E -->|No| G[Move Split Before Block]
    
    F --> H[Add Closing Markers]
    G --> I[Add Opening Markers]
    
    H --> J[Complete Split]
    I --> J
    C --> J
```

## Citation-Aware Splitting

For Perplexity responses with citations, the splitting algorithm ensures citations remain functional:

```mermaid
flowchart TD
    A[Long Citation Content] --> B[Split at 4090 chars]
    B --> C[Analyze Citation References]
    
    C --> D[Part 1: Citations 1-3]
    C --> E[Part 2: Citations 4-6]
    
    D --> F[Create Embed 1]
    E --> G[Create Embed 2]
    
    F --> H[Footer: "Web search results"]
    G --> I[Footer: "Web search results (continued)"]
    
    H --> J[Send Embed 1]
    I --> K[Send Embed 2]
    
    J --> L[All Citations Clickable]
    K --> L
```

## Code Examples

### Regular Message Splitting

```python
async def send_split_message(channel, message, deps, suppress_embeds=False):
    """Split long messages at optimal boundaries."""
    if len(message) <= 2000:
        await channel.send(message, suppress_embeds=suppress_embeds)
        return
    
    # Find optimal split point
    split_point = find_optimal_split_point(message, len(message) // 2)
    
    # Adjust for code blocks
    before, after = adjust_split_for_code_blocks(message, split_point)
    
    # Send parts
    await channel.send(before.strip(), suppress_embeds=suppress_embeds)
    if after.strip():
        await send_split_message(channel, after.strip(), deps, False)
```

### Embed Splitting with Citations

```python
async def send_split_message_with_embed(channel, message, deps, embed, citations):
    """Split embed content while preserving citations."""
    if len(message) <= 4090:
        await channel.send("", embed=embed)
        return
    
    # Split content
    split_point = find_optimal_split_point(message, 4090)
    part1, part2 = adjust_split_for_code_blocks(message, split_point)
    
    # Send first part with original embed
    await channel.send("", embed=embed)
    
    # Process remaining parts
    if part2 and citations:
        remaining_citations = find_citations_in_text(part2, citations)
        if remaining_citations:
            continuation_embed = create_citation_embed(
                part2, remaining_citations, 
                footer_text="Web search results (continued)"
            )
            await channel.send("", embed=continuation_embed)
```

## Split Point Algorithm

### Finding Optimal Boundaries

```python
def find_optimal_split_point(message: str, target_index: int) -> int:
    """Find the best place to split a message near the target index."""
    
    # Search window around target (±50 characters)
    search_start = max(0, target_index - 50)
    search_end = min(len(message), target_index + 50)
    search_area = message[search_start:search_end]
    
    # Priority 1: Newline boundaries
    newlines = [i for i, char in enumerate(search_area) if char == '\n']
    if newlines:
        return search_start + max(newlines) + 1
    
    # Priority 2: Sentence endings
    sentences = []
    for i, char in enumerate(search_area):
        if char in '.!?' and i < len(search_area) - 1:
            if search_area[i + 1] == ' ':
                sentences.append(i + 1)
    if sentences:
        return search_start + max(sentences)
    
    # Priority 3: Word boundaries
    words = [i for i, char in enumerate(search_area) if char == ' ']
    if words:
        return search_start + max(words)
    
    # Fallback: Use target index
    return target_index
```

## Best Practices

### For Developers

1. **Always check content length** before sending
2. **Use appropriate limits** (2000 for messages, 4096 for embeds)
3. **Preserve formatting** when splitting
4. **Test with long content** to verify splitting works
5. **Handle edge cases** like very long words or URLs

### For Bot Configuration

1. **Set reasonable response limits** in AI API calls
2. **Monitor splitting frequency** in logs
3. **Test citation distribution** with long Perplexity responses
4. **Verify code block preservation** works correctly

## Troubleshooting

### Common Issues

**Messages cut off mid-word**:
- Check `find_optimal_split_point()` implementation
- Verify word boundary detection is working

**Code blocks broken across messages**:
- Ensure `adjust_split_for_code_blocks()` is called
- Check code block detection patterns

**Citations not working in split embeds**:
- Verify citation mapping is preserved
- Check that continuation embeds include relevant citations

**Infinite recursion in splitting**:
- Check recursion depth limits (max 10)
- Ensure fallback truncation works

### Performance Considerations

- **Split point calculation**: O(n) where n is search window size
- **Code block detection**: O(n) where n is message length  
- **Citation mapping**: O(c) where c is number of citations
- **Memory usage**: Minimal additional overhead

## Advanced Configuration

### Customizing Split Behavior

```python
# Adjust search window for split points
SPLIT_SEARCH_WINDOW = 50  # characters around target

# Maximum recursion depth for splitting
MAX_SPLIT_RECURSION = 10

# Preferred split characters (in priority order)
SPLIT_PRIORITIES = ['\n', '. ', '! ', '? ', ' ']
```

### Monitoring Split Operations

```python
# Log split operations for debugging
logger.debug(f"Splitting message: {len(message)} chars at depth {depth}")
logger.debug(f"Split point found at index {split_point}")
logger.debug(f"Parts: {len(part1)} + {len(part2)} chars")
```
