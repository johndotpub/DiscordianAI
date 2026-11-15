# API contract

What this bot actually sends to the OpenAI-compatible chat provider and Perplexity, what
those services actually return, and what that means for the code. Every row is either cited
to a vendor page or **probed live** with `scripts/probe_providers.py` on 2026-10-28.
The shipped chat provider is Ollama Cloud (`https://ollama.com/v1/`); OpenAI is a supported
alternative reached through the same client.

Rule for contributors: if you change a request parameter, a model name, or an error
branch, update this file and run the probe. A claim without a citation or a probe result
is not a contract.

---

## OpenAI-compatible chat provider

| Item | Value | Source |
|---|---|---|
| Endpoint used | `POST /v1/chat/completions` | `src/openai_processing.py` |
| Base URL sent | whatever `OPENAI_API_URL` says; the shipped default is `https://ollama.com/v1/` | `config.ini.example` |
| Model sent | whatever `GPT_MODEL` says; the shipped default is `deepseek-v4.1-flash:1017` | `config.ini.example` |
| Output cap parameter | `max_tokens` on Ollama-compatible hosts (`ollama.com`, `localhost`, `127.0.0.1`); `max_completion_tokens` on `api.openai.com` | `src/openai_processing.py` |
| What the output cap covers | **visible output plus reasoning tokens.** A cap consumed by reasoning returns HTTP 200 with `finish_reason: length` and `content: ""` | probe |
| `reasoning_effort` | sent from `REASONING_EFFORT` only when non-empty (default `high`). It is a reasoning-model parameter; whether a model accepts it is provider-defined. `low`, `high`, and `max` are accepted by the shipped model, and `none` disables thinking | provider reference |
| Cloud-model features | structured outputs, log probabilities, and `tool_choice` are not supported by cloud models and the bot does not send them | provider reference |
| Web tools | `tools` carries `web_search` and `web_fetch` function schemas only when the base URL is Ollama-compatible and `WEB_TOOLS` is true; the model may request up to four tool rounds | `src/openai_processing.py`, `src/web_tools.py` |
| OpenAI alternative | change `OPENAI_API_URL` to `https://api.openai.com/v1/`, set an `sk-` key, and choose a model; chat requests then send `max_completion_tokens` and `reasoning_effort`, not `max_tokens` | OpenAI Chat reference |
| Maximum completion tokens | 128,000 (the bot's documented ceiling) | probe (error text) |
| Oversized output cap | HTTP 400, `error.type: invalid_request_error`, `error.code: invalid_value`, message `max_tokens is too large: … This model supports at most 128000 completion tokens` | probe |
| Prompt-too-long | code `context_length_exceeded` is the documented family, **not verified here** — probing it means paying to send a 128k-token prompt. Treat as `UNVERIFIED` until someone does | unverified |
| Idempotency key | no documented header for chat completions. Retries must therefore be limited to requests that provably never reached the server | unverified |

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
| Catalogue | `GET /v1/models` lists 54 models and exactly one Sonar model, `perplexity/sonar` | probe |
| Legacy interface | Sonar Chat Completions still answers 200 with `citations` and `search_results`; it is not the current catalogue or the interface this bot uses | probe |
| Request fields | `model`, `instructions` (system prompt plus the URL-fetch policy), `input` (history and current user message, no system role), `max_output_tokens`, `tools: [{"type": "web_search"}, {"type": "fetch_url"}]`, `extra_body: {"max_steps": 3}` (the SDK has no `max_steps` kwarg) | probe + code |
| Sampling | no `temperature` is sent | probe + code |
| Response shape | `output` array of items | probe |
| `search_results` item | `results[]` with `id`, `url`, `title`, `snippet`, `date`, `last_updated`, `source`; `id` is the 1-based marker number used in the answer as `[1]`, `[2]` | probe |
| `message` item | `role: "assistant"`, `content: [{"type": "output_text", "text": "…"}]` | probe |
| `fetch_url_results` item | fetched pages under `contents[]` (or `results[]` on older shapes), each with `url` and `title`; citation markers resolve the same way as search results | code |
| No-search response | `output` contains only the `message` item; there is no `search_results` item | probe |
| Usage | `input_tokens`, `output_tokens`, `total_tokens`, and `cost` with input, output, tool-call, and total cost | probe |
| Invalid model | HTTP **400** with `error.type: invalid_request`, `error.code: 400`, message `validation failed: model "…" is not supported`. The legacy path used `invalid_model`. Classify as a deterministic validation error and never retry | probe |
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
   the tool loop at three steps and travels in `extra_body` because the SDK has no
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
set -a && . ~/.config/environment.d/hermes.conf && set +a
.venv/bin/python scripts/probe_providers.py
```

The probe prints status codes, header names, response key shapes and token counts. It
never prints credentials. It makes eleven calls: six successful (small, cheap) and five
deliberate error probes, including the Agent API, its alias, the unversioned path, and an
invalid model. Run it after any provider upgrade, model change, or SDK bump.
