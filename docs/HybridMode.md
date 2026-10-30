# Smart AI Mode: Advanced GPT-6 + Perplexity Integration

## Overview

DiscordianAI features an AI orchestration system with evidence-based routing, conversation consistency,
and three flexible operation modes:

1. **OpenAI Only** - Use GPT-6 for all responses
2. **Perplexity Only** - Use `perplexity/sonar` with web search for all responses
3. **Smart Hybrid** - Choose the best AI for each message with an evidence model

Hybrid routing is not a list of word patterns. The router asks whether a message refers to something whose
value can change and whose answer is expected to be verifiable. If it does, the message needs the live web.
If it does not, the local model answers it.

## Evidence-Based Routing

Each message is scored once by `src/routing/` before any provider is called. The score is a signed trace of
two evidence classes:

- **Bearing** — a mutable referent: a status predicate, a change or outcome event, a price or quantity
  shape, a version shape, a volatile topic noun. Bearing may decide the route.
- **Framing** — the shape of the request: question, imperative, opinion, creative, social, greeting, or a
  proper name. Framing is multiplied by `lambda_framing < 1` and never decides alone.

There are no early returns and no branch order that can hide a live-data cue. The pipeline is:

```
views    = normalise surface + folded text (case preserved for entities)
overrides= URL, "search the web", "from memory", and similar explicit instructions
cues     = bearing and framing evidence
score    = sum(bearing) + lambda_framing * sum(framing)
p_web    = sigmoid((score - t_mid) / temperature)
route    = web     if p_web >= tau
           local   if p_web <= tau_local
           unsure  otherwise
if no bearing cue and no override: route = local
```

Two rules keep the model honest:

- **No bearing cue means no web route.** A question mark or a proper name is not enough. *"What is the
  capital of France?"* stays local because the answer does not change.
- **Framing cannot decide alone.** Social text such as "thanks" or "best regards" carries negative framing
  weight and will not turn into a search.

The bundled English lexicon supplies topic terms; structural shapes supply status, change, release,
version, money, time, code, and URL cues. Adding a term is a lexicon data change, not a code change.

### What routes where

| Message | Route | Why |
|---|---|---|
| "What's the latest news?" | Web | Volatile topic plus current-time deixis |
| "Is github down?" | Web | Status predicate about a live service |
| "What's $AAPL trading at right now?" | Web | Money shape plus current-time framing |
| "Write a poem about winter" | Local | Creative framing, no bearing cue |
| "What is the capital of France?" | Local | Stable fact; question framing alone cannot decide |
| "Here is a traceback, what is wrong?" | Local | Supplied code artefact cancels volatile cues |

### Follow-up inheritance

A follow-up is a short message (at most six tokens) that is an anaphor, a bare continuation, or begins with
a coordinator, and it must have an assistant turn at gap <= 1 in the same conversation. The previous route
then applies at +2/-2. A bearing cue in the new message wins, and a topic shift cancels inheritance.

A word such as "also" or "more" inside a fresh question does not turn that question into an early return.
There is no separate follow-up regex list; inheritance is one cue in the same score.

### Example flow

```
User: "What's the weather in Tokyo today?"
→ Web decision (volatile topic + time deixis)
→ Perplexity answer with citations

User: "Tell me more"
→ Follow-up inherits the web route from the same conversation
→ Perplexity answers with the earlier turn in view
```

## Message Flow Architecture

```mermaid
flowchart TD
    A[Discord Message Received] --> B{Bot Mentioned?}
    B -->|No| Z[Ignore Message]
    B -->|Yes| C[Rate Limit + Guardrails]
    C -->|Failed| D[Send Rate Limit Message]
    C -->|Passed| E[Build AIRequest]

    E --> F{Mode Selector}
    F -->|OpenAI Only| G[OpenAI Processing\n(GPT-6 family)]
    F -->|Perplexity Only| H[Perplexity Processing\n(Agent API)]
    F -->|Hybrid| R[Build RouterInput\n+ one route decision]

    R -->|web| H
    R -->|local| G

    G --> OW[OpenAI Response]
    OW --> WI{Indicates web-inability?}
    WI -->|Yes, Perplexity not tried| H
    WI -->|Yes, Perplexity already failed| U[Return local answer]
    WI -->|No| U
    H --> PR[Agent API Response + Citations]

    U --> W[send_formatted_message]
    PR --> V[Citation Embed Formatter]
    V --> W

    W --> X{Contains Embeds?}
    X -->|Yes| Y{Embed > Limits?}
    X -->|No| Z1{Message > 2000 chars?}

    Y --> CC[Split Embed + Citations]
    Z1 --> DD[Split Plain Message]
    CC --> BB[✅ Response Complete]
    DD --> BB
```

### Key anti-duplication features

1. **Single entry point**: all responses go through `send_formatted_message`.
2. **Explicit returns**: each successful send exits the function.
3. **Embed priority**: Perplexity answers with citations try the embed first, then a regular message.
4. **One attempt per provider**: an `AttemptLedger` prevents a second Perplexity call in the same request.

### Model guardrails

- `api_validation.validate_openai_config()` warns when `GPT_MODEL` falls outside the documented GPT model
  families; unknown names do not block startup.
- Perplexity calls send `model`, `instructions`, `input`, `max_output_tokens`, and the `web_search` tool.
  `perplexity/sonar` is the default, sampling is handled by the API, and no `temperature` is sent.
- Citations come from the Agent API `search_results` item: each result's 1-based `id` maps to the `[n]`
  marker in the answer text.

## Routing Configuration

```ini
[Orchestrator]
# heuristic (default) or model; the Clef model router is not implemented yet
ROUTER_MODE=heuristic

# Web-route probability thresholds by channel kind
ROUTER_WEB_THRESHOLD_CHANNEL=0.10
ROUTER_WEB_THRESHOLD_ANNOUNCE=0.07
ROUTER_WEB_THRESHOLD_DM=0.20

# How many recent messages a follow-up may inspect
LOOKBACK_MESSAGES_FOR_CONSISTENCY=6
```

| Setting | Default | Description |
|---|---|---|
| `ROUTER_MODE` | `heuristic` | Selects the router implementation. `model` raises until the Clef seam is built. |
| `ROUTER_WEB_THRESHOLD_CHANNEL` | 0.10 | Web-route probability threshold in ordinary channels. |
| `ROUTER_WEB_THRESHOLD_ANNOUNCE` | 0.07 | Web-route probability threshold in announcement channels. |
| `ROUTER_WEB_THRESHOLD_DM` | 0.20 | Web-route probability threshold in direct messages. |
| `LOOKBACK_MESSAGES_FOR_CONSISTENCY` | 6 | How many recent messages a follow-up may inspect; `0` disables the lookup. |
| `MAX_HISTORY_PER_USER` | 50 | Maximum conversation entries stored per user. |
| `USER_LOCK_CLEANUP_INTERVAL` | 3600 | How often to clean up inactive user locks, in seconds. |

`ENTITY_DETECTION_MIN_WORDS=10` is parsed into config but is not consulted by the current router; changing
it has no runtime effect.

### Threshold selection

The router always uses the threshold for the current channel kind: DM (`ROUTER_WEB_THRESHOLD_DM`),
announcement channel (`ROUTER_WEB_THRESHOLD_ANNOUNCE`), or ordinary channel
(`ROUTER_WEB_THRESHOLD_CHANNEL`). Lowering a threshold makes borderline bearing messages more likely to
search; raising it makes them more likely to stay local.

## Caching and Degradation

- The route decision is built even when a response comes from cache.
- Cache keys include the service (`openai` or `perplexity`), router id, policy version, decision source,
  function, route salt, and degraded flag. A web answer and a local answer never share an entry.
- An unsure decision is not cached. A local decision that carried bearing evidence is not cached. A URL
  instruction is not cached.
- A degraded fallback (web failed, local answer returned) is stored with `degraded=true` and is reachable
  only from the fallback path.
- A missing conversation manager or a history lookup that raises still produces a decision with empty
  context, and the model answer is delivered normally.

## Setup Instructions

### 1. Get API keys (as needed)

**OpenAI API key** (for GPT-6):
- Go to https://platform.openai.com/api-keys
- Create a new API key

**Perplexity API key** (for web search):
- Go to https://www.perplexity.ai/settings/api
- Generate an API key

### 2. Choose your configuration

Copy `config.ini.example` to `config.ini` and toggle the keys for your desired mode:
- **Hybrid**: Provide both `OPENAI_API_KEY` and `PERPLEXITY_API_KEY`.
- **OpenAI Only**: Set `PERPLEXITY_API_KEY` blank.
- **Perplexity Only**: Set `OPENAI_API_KEY` blank.

Environment variables with the same names override `config.ini`, so production deployments can keep
secrets out of the file system.

### 3. Test it

- "Hello!" -> local GPT-6
- "What's the latest AI news?" -> Perplexity
- "Tell me about today's weather" -> Perplexity
- "How do I learn Python?" -> local GPT-6

## Fallback Behavior

The hybrid orchestrator (`smart_orchestrator.py`) provides bounded fallback between services:

- **OpenAI failure -> Perplexity**: When the local answer is empty, the orchestrator may try Perplexity
  once for a web-enabled fallback.
- **Perplexity failure -> OpenAI**: When the web answer fails, the orchestrator falls back to OpenAI for a
  standard completion and marks the answer degraded.
- **Web-inability reroute**: If OpenAI says it cannot browse the web and Perplexity has not been tried in
  this request, the orchestrator reroutes once. If Perplexity already failed, the local answer is returned
  with a warning instead of a second Perplexity call.
- **Both unavailable**: Returns the `both_services_unavailable` message
  (`"🔧 All AI services are temporarily unavailable. Please try again later."`).

Both services share the same retry policy via `retry_with_backoff`:

- 2 attempts max (1 initial + 1 retry) for transient errors (network/connection errors, connect timeouts,
  429, 5xx)
- `insufficient_quota`, authentication errors, and read timeouts bail immediately
- The single retry waits a random 0-1s (full jitter over the base delay); a 429 can instead honour
  `Retry-After` up to 30s
- A 90s `max_elapsed` deadline stops retries even when an attempt remains
- SDK-level `max_retries=0` prevents nested retry multiplication

## Cost Considerations

**Routing has no cost cap.** The router decides whether a message needs live data on the strength of the
message itself — there is no budget, no per-hour search allowance and no price model in the decision. Search
volume therefore follows what people ask, not how much you are willing to spend. If you need a ceiling, it
belongs at the Discord or provider level, not in the router, because a router that stops searching when a
counter runs out answers live questions from stale weights and cannot tell you it did so.

## Cost Considerations

- **GPT-6**: Higher cost per token but strong reasoning on stable knowledge and code.
- **Perplexity**: Includes citations and live web data but is reserved for messages that carry bearing
  evidence.
- The bot chooses local answers for stable knowledge and creative work, and web answers for live facts.

## Monitoring & Debugging

### Routing decision logs

Each hybrid decision logs one content-free line:

```
INFO Routing decision: {'route': 'web', 'band': 'confident', 'service': 'perplexity', 'score': 4.2,
'threshold': 0.1, 'reasons': ['topic.volatile', 'time.deixis'], 'router_id': 'heuristic@1',
'policy_version': '1', 'latency_ms': 0.14}
```

Message text and matched entity text are not logged.

### Provider logs

```
INFO Routing to Perplexity
INFO Perplexity response generated successfully (245 chars)
```

```
INFO Routing to OpenAI
WARNING Perplexity failed, falling back to OpenAI
```

```
WARNING Perplexity already failed in this request; returning the local answer without a second attempt
```

## Thread-Safe Architecture

DiscordianAI uses a thread-safe architecture for concurrent users:

- **Per-conversation locking**: history operations are atomic for one DM, guild channel, or thread.
- **Scoped state**: history and cache keys are keyed per conversation, never per user.
- **Memory management**: inactive conversations and locks are evicted.
- **Metadata tracking**: each assistant turn records the service and model that produced it, so follow-up
  inheritance reads the actual route rather than guessing it.

## Customization

There is no runtime per-guild vocabulary. Routing changes are either configuration (thresholds and mode) or
a release that updates the bundled lexicon in `src/routing/data/lexicon.en.json`.

### Production deployment tips

1. **Monitor memory**: watch cleanup logs to confirm inactive conversations are evicted.
2. **Adjust history**: increase `MAX_HISTORY_PER_USER` for longer context.
3. **Tune thresholds**: lower a channel-kind threshold only when missed live questions hurt more than
   needless searches in that surface.
