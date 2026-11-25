# API contract

What this bot actually sends to the OpenAI-compatible chat provider and Perplexity, what
those services actually return, and what that means for the code. Every row is cited to a
vendor page, measured with `scripts/probe_providers.py`, or marked **UNVERIFIED**.
The 2026-10-28 probe used an OpenAI key and the GPT-5 family; rows measured that way are
labelled **OpenAI-measured**. The shipped chat provider is now Ollama Cloud
(`https://ollama.com/v1/`), so those measurements are not a measurement of the default
model. OpenAI remains a supported alternative through the same client.

Rule for contributors: if you change a request parameter, a model name, or an error
branch, update this file and run the probe. A claim without a citation or a probe result
is not a contract.

---

## OpenAI-compatible chat provider

| Item | Value | Source |
|---|---|---|
| Endpoint used | `POST /v1/chat/completions` | `src/providers/openai_chat.py` |
| Base URL sent | whatever `OPENAI_API_URL` says; the shipped default is `https://ollama.com/v1/` | `config.ini.example` |
| Model sent | whatever `GPT_MODEL` says; the shipped default is `deepseek-v4.1-flash:1017` | `config.ini.example` |
| Output cap parameter | `max_tokens` on Ollama-compatible hosts (`ollama.com`, `localhost`, `127.0.0.1`); `max_completion_tokens` on every other OpenAI-compatible host, including `api.openai.com` | `src/providers/openai_chat.py` |
| What the output cap covers | **visible output plus reasoning tokens.** A cap consumed by reasoning returns HTTP 200 with `finish_reason: length` and `content: ""` | OpenAI-measured (2026-10-28) |
| `reasoning_effort` | sent from `REASONING_EFFORT` only when non-empty (default `high`). It is a reasoning-model parameter; whether a model accepts it is provider-defined. `low`, `high`, and `max` are accepted by the shipped model, and `none` disables thinking | provider reference; the exact Ollama Cloud tag is UNVERIFIED |
| Cloud-model features | structured outputs, log probabilities, and `tool_choice` are not supported by cloud models and the bot does not send them | provider reference; not re-probed on Ollama Cloud |
| Web tools | `tools` carries `web_search` and `web_fetch` function schemas only when the base URL is Ollama-compatible and `WEB_TOOLS` is true; the loop allows four rounds, offers no tools on the fourth so the model must answer, executes at most three calls per round, and caps total tool output | `src/providers/openai_chat.py`, `src/web_tools.py` |
| Image content | When a message carries images, the current user message becomes a content list of one `text` part followed by one `image_url` part per image, with the part's `url` field set to `data:<mime>;base64,<payload>`. History turns remain text-only | `src/message_builder.py`, `src/image_attachments.py` |
| OpenAI alternative | change `OPENAI_API_URL` to `https://api.openai.com/v1/`, set an `sk-` key, and choose a model; chat requests then send `max_completion_tokens` and `reasoning_effort`, not `max_tokens` | OpenAI Chat reference |
| Maximum completion tokens | 128,000 provider-reported for the probed OpenAI model; the bot enforces the same fixed 128,000 validation ceiling for both providers, independent of `CONTEXT_WINDOW` | OpenAI-measured (error text); Ollama Cloud value UNVERIFIED |
| Oversized output cap | HTTP 400, `error.type: invalid_request_error`, `error.code: invalid_value`, message `max_tokens is too large: … This model supports at most 128000 completion tokens` | OpenAI-measured (2026-10-28) |
| Prompt-too-long | code `context_length_exceeded` is the documented family, **not verified here** — probing it means paying to send a 128k-token prompt. Treat as `UNVERIFIED` until someone does | unverified |
| Idempotency key | no documented header for chat completions. Retries must therefore be limited to requests that provably never reached the server | UNVERIFIED |

### Default chat model (Ollama Cloud)

The shipped default is `deepseek-v4.1-flash:1017` on `https://ollama.com/v1/`. Only these
facts are verified for it:

- The Ollama library page (`https://ollama.com/library/deepseek-v4.1-flash`, accessed
  2026-11-23) lists a 1M-token context window and the capabilities vision, tools, and
  thinking for `deepseek-v4.1-flash`. The page lists the tags
  `deepseek-v4.1-flash:cloud` and `deepseek-v4.1-flash:1017-cloud`; the configured tag
  `deepseek-v4.1-flash:1017` is not shown, so the exact tag is **UNVERIFIED**.
- The library page does not publish a maximum output-token count. The 128,000 ceiling above
  is OpenAI-measured and is enforced by this bot for both providers; the default model's
  own limit is **UNVERIFIED**.
- The request shape below is code-verified. Whether the configured tag accepts every field
  in it is **UNVERIFIED** until the probe is run against Ollama Cloud.

### Consequences for this codebase

1. `max_tokens` must never be set low "to save money": on a reasoning model the
   reasoning budget is consumed first and the reply comes back as an empty string with
   `finish_reason: length`. The empty-content reroute path exists — it is a safety net, not
   a licence to set the cap small.
2. Token budgeting must reserve headroom for reasoning, not just for the visible answer.
3. `is_supported_openai_model` accepts any non-empty model identifier; provider model ids
   are not gated.
4. Classify `invalid_value` and `invalid_request_error` as deterministic configuration
   faults: retrying them wastes an attempt and 2–4 seconds of the user's time.
5. Image requests are local-only: they force the chat route, keep the native tools, and are
   never sent to Perplexity. A chat-provider failure on an image request has no web fallback.

---

## Perplexity

The bot uses the current Agent API, not Sonar Chat Completions. The OpenAI SDK's
`responses.create()` is pointed at the versioned alias, so the request path is
`/v1/responses`.

| Item | Value | Source |
|---|---|---|
| Canonical endpoint | `POST https://api.perplexity.ai/v1/agent` — **verified 200** | probe |
| SDK path used | `POST https://api.perplexity.ai/v1/responses` — **verified 200**, same response shape | probe |
| Unversioned SDK path | `POST https://api.perplexity.ai/responses` returned **404**; the client must include `/v1` | probe |
| Model sent | `perplexity/sonar` | probe + `GET /v1/models` |
| Context window | 128K tokens; `PERPLEXITY_CONTEXT_WINDOW` defaults to 128,000. The figure comes from the former Sonar model page (`https://docs.perplexity.ai/docs/sonar/models/sonar`, now redirecting to the Agent API migration guide); the Agent API models page publishes no context figure, so 128K is **UNVERIFIED** there | vendor citation, not re-probed |
| Catalogue | `GET /v1/models` lists 54 models and exactly one Sonar model, `perplexity/sonar` | probe |
| Legacy interface | Sonar Chat Completions still answers 200 with `citations` and `search_results`; it is not the current catalogue or the interface this bot uses | probe |
| Request fields | `model`, `instructions` (system prompt plus the URL-fetch policy), `input` (history and current user message, no system role), `max_output_tokens`, `tools: [{"type": "web_search"}, {"type": "fetch_url"}]`, `extra_body: {"max_steps": 4}` (the SDK has no `max_steps` kwarg) | probe + `src/providers/perplexity.py` |
| Sampling | no `temperature` is sent | probe + code |
| Response shape | `output` array of items | probe |
| `search_results` item | `results[]` with `id`, `url`, `title`, `snippet`, `date`, `last_updated`, `source`; `id` is the 1-based marker number used in the answer as `[1]`, `[2]` | probe |
| `message` item | `role: "assistant"`, `content: [{"type": "output_text", "text": "…"}]` | probe |
| `fetch_url_results` item | fetched pages under `contents[]` (or `results[]` on older shapes), each with `url` and `title`; citation markers resolve the same way as search results | code |
| No-search response | `output` contains only the `message` item; there is no `search_results` item | probe |
| Usage | `input_tokens`, `output_tokens`, `total_tokens`, and `cost` with input, output, tool-call, and total cost | probe |
| Invalid model | HTTP **400**. The recorded probe response was `{"error": {"type": "invalid_request", "code": 400, "message": "validation failed: model \"sonar\" is not supported"}}`; the SDK exposes the inner error object and reports `code` as the string `"400"`. The bot classifies a 400 as a configuration error when the structured error type or code is `invalid_model` or `model_not_found`, when `param` is `model`, or when the message combines the word `model` with `is not supported`, `not found`, or `does not exist`. A 400 about anything else stays neutral. Never retry | probe + code |
| Rate limit | HTTP **429**; classified as a rate limit and handled by the shared retry policy | probe + code |
| Attribution header | `X-Pplx-Integration: discordian-ai` accepted, 200, no behaviour change | probe |

### Consequences for this codebase

1. `PERPLEXITY_MODELS` now lists the current catalogue entry, `perplexity/sonar`. An unknown
   name still only warns, because the provider may add models before the list is updated
   here.
2. The system prompt travels as `instructions`, not as a system message inside `input`.
   History and the current turn travel in `input`.
3. `max_output_tokens` replaces `max_tokens`, and `tools` always asks for `web_search`
   and `fetch_url` because this path exists for live-data questions. `max_steps` bounds
   the tool loop at four steps and travels in `extra_body` because the SDK has no
   parameter for it.
4. Citation markers are mapped by the `search_results[].id`, not by array position, so a
   reordered result list cannot misattribute a source.
5. A response without `search_results` is valid: the parser returns the message text and an
   empty citation map instead of failing.
6. `usage.cost` is available but not logged today. Do not add a second accounting scheme to
   report spend.

---

## How to re-verify

```bash
# export the provider credentials for your deployment, then:
.venv/bin/python scripts/probe_providers.py
```

The probe prints status codes, header names, response key shapes and token counts. It
never prints credentials. It makes eleven calls: six successful (small, cheap) and five
deliberate error probes, including the Agent API, its alias, the unversioned path, and an
invalid model. Run it after any provider upgrade, model change, or SDK bump.
