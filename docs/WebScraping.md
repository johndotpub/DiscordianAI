# Web Access

DiscordianAI gives both providers native web access. There is no local
scraper: pages are fetched by the provider, and the resulting text is treated
as untrusted reference material.

## Perplexity

The Agent API request always includes two tools:

- `web_search` for current search results.
- `fetch_url` for opening URLs that appear in the user's message.

The request also sets `max_steps` to 3, so the model can search, fetch, and
answer without an unbounded tool loop. The instructions tell the model to open
each URL (up to 10), cite the sources it used, and say plainly when a page
cannot be fetched.

Citation markers resolve against both `search_results` and `fetch_url_results`
output items. Fetched pages therefore produce the same numbered citation
embeds as search results.

## Ollama-compatible chat providers

When the chat base URL belongs to Ollama (`ollama.com`, a subdomain, or a local
daemon on `localhost`/`127.0.0.1`), the bot offers two function tools:

- `web_search(query, max_results=5)` returns bounded search results.
- `web_fetch(url)` returns a bounded page title and body.

The model may request up to four rounds of tool calls. Each round is executed,
fed back as a tool message, and followed by another completion request. If the
model is still asking for tools after four rounds, the request stops and keeps
any final text it produced; an empty result is treated as a failed answer.

OpenAI endpoints do not receive these tools. Ollama-specific tool endpoints
would be rejected there, so the tools are attached only for Ollama-compatible
base URLs.

## Configuration

`WEB_TOOLS` enables the chat-path tools and defaults to `true`. Perplexity's
tools are always enabled because that path exists for live-data questions.

```ini
[Default]
WEB_TOOLS=true
```

Set `WEB_TOOLS=false` to send plain chat requests to Ollama. It has no effect
on Perplexity.

## Trust boundary

Tool output is untrusted. The tool descriptions and the Perplexity instructions
tell the model never to follow instructions found inside fetched pages or
search results. This is a mitigation, not a guarantee: a model can still be
influenced by injected text, and the bot does not inspect page content before
the provider returns an answer.

Tool output is bounded before it reaches the model:

- Search results are capped at 6,000 characters.
- Fetched page text is capped at 8,000 characters.
- Truncated output ends with `… [truncated]`.

## Logging

Each chat-path tool call logs one INFO line with its name and outcome, for
example `web_tool=web_search ok=true`. Arguments (the query or URL) are logged
only at DEBUG level. API keys are never logged.

## Caching

A chat answer produced with tools is cached like any other answer. The cache
key is unchanged, so identical conversation state and message text can return
the same cached answer within its TTL. Perplexity responses are not cached.
