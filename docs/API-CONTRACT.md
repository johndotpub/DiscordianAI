# API contract

What this bot actually sends to OpenAI and Perplexity, what those services actually
return, and what that means for the code. Every row is either cited to a vendor page or
**probed live** with `scripts/probe_providers.py` on 2026-10-28.

Rule for contributors: if you change a request parameter, a model name, or an error
branch, update this file and run the probe. A claim without a citation or a probe result
is not a contract.

---

## OpenAI

| Item | Value | Source |
|---|---|---|
| Endpoint used | `POST /v1/chat/completions` | `src/openai_processing.py` |
| Model sent | whatever `GPT_MODEL` says; the deployment uses `gpt-5` | `config.ini` |
| Newer models accepted by the API | `gpt-5.4` answered normally at probe time, so the API is not the limit — our allowlist is | probe |
| Output cap parameter | `max_completion_tokens` (not `max_tokens`, which is deprecated and incompatible with o-series) | OpenAI Chat reference |
| What the output cap covers | **visible output plus reasoning tokens.** A cap of 16 tokens on `gpt-5` returned HTTP 200 with `finish_reason: length` and `content: ""` — the whole budget went to reasoning | probe |
| Maximum completion tokens on `gpt-5` | 128,000 | probe (error text) |
| `reasoning_effort` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; not every model supports every value. `gpt-6-astra` rejects `none` | OpenAI reference + changelog |
| `verbosity` | `low`, `medium`, `high` | OpenAI reference |
| Oversized output cap | HTTP 400, `error.type: invalid_request_error`, `error.code: invalid_value`, message `max_tokens is too large: … This model supports at most 128000 completion tokens` | probe |
| Prompt-too-long | code `context_length_exceeded` is the documented family, **not verified here** — probing it means paying to send a 128k-token prompt. Treat as `UNVERIFIED` until someone does | unverified |
| Rate-limit headers on success | `x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`, `x-ratelimit-reset-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-tokens` | probe |
| `Retry-After` | not sent on 2xx; expected on 429, **not observed** | unverified |
| Idempotency key | no documented header for chat completions. Retries must therefore be limited to requests that provably never reached the server | unverified |
| Chat Completions status | "remains supported" indefinitely; Responses is recommended for new work and gives better reasoning results and 40–80% better cache utilisation | OpenAI migration guide |
| Assistants API | sunset 2026-08-26 | OpenAI changelog |

### Consequences for this codebase

1. `max_completion_tokens` must never be set low "to save money": on a reasoning model the
   reasoning budget is consumed first and the reply comes back as an empty string with
   `finish_reason: length`. The empty-content reroute path exists — it is a safety net, not
   a licence to set the cap small.
2. Token budgeting must reserve headroom for reasoning, not just for the visible answer.
3. `is_supported_openai_model` rejecting `gpt-5.4` or `gpt-6-*` is a *names* problem, not an
   API problem. Validate shape, warn, and never block on an unknown model.
4. Classify `invalid_value` and `invalid_request_error` as deterministic configuration
   faults: retrying them wastes an attempt and 2–4 seconds of the user's time.

---

## Perplexity

| Item | Value | Source |
|---|---|---|
| Path used by the SDK | `https://api.perplexity.ai/chat/completions` — **verified working** | probe |
| Canonical path in current docs | `POST /v1/sonar` — **also verified working**, same response shape | probe + OpenAPI |
| Models | `sonar`, `sonar-pro`, `sonar-deep-research`, `sonar-reasoning-pro` | OpenAPI enum |
| `max_tokens` | integer, `0 < n ≤ 128000` | OpenAPI |
| `reasoning_effort` | `minimal`, `low`, `medium`, `high` only. Sending `xhigh` returned HTTP 400 | OpenAPI + probe |
| Response fields | `choices`, `created`, `citations` (list of URLs), `search_results` (list of objects), `usage` with `cost` and `search_context_size` | probe |
| `search_results[]` keys | `title`, `url`, `date`, `last_updated`, `snippet`, `source`, `place_metadata` | probe |
| Invalid model | HTTP **400** with `error.type: invalid_model`, `error.code: 400`. Not 422 — the OpenAPI file documents 422 for validation errors, but the live service answers 400 | probe (live beats spec) |
| Rate-limit headers | `x-ratelimit-limit`, `-remaining`, `-reset` (epoch seconds), `-used`. Observed limit on this account: **1** | probe |
| Attribution header | `X-Pplx-Integration: discordian-ai` accepted, 200, no behaviour change | probe |

### Consequences for this codebase

1. The known-model list now matches this enum. An unknown name still only warns, because
   the provider may add models before the list is updated here.
2. A bad model name surfaces as **400 / `invalid_model`**, so the classifier needs that
   branch; treating it as an unknown error means a permanent misconfiguration is retried
   and then reported to the user as "unexpected error".
3. `x-ratelimit-limit: 1` means a Perplexity request must never be issued concurrently with
   another on the same account. The scraper's per-host politeness and the retry policy both
   need to respect this, or the second request returns 429 and the first answer is wasted.
4. `search_results` carries page titles, so citation embeds can show "Title — domain"
   instead of bare URLs. Optional enhancement; the test doubles must model both fields
   either way.
5. `usage.cost` is returned and discarded today. Logging it makes spend visible per message.

---

## How to re-verify

```bash
set -a && . ~/.config/environment.d/hermes.conf && set +a
.venv/bin/python scripts/probe_providers.py
```

The probe prints status codes, header names, response key shapes and token counts. It
never prints credentials. It makes seven calls: five successful (small, cheap) and two
deliberate error probes. Run it after any provider upgrade, model change, or SDK bump.
