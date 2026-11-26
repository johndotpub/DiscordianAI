# API Parameter Validation

## Overview

`src/api_validation.py` checks configuration before the bot starts. It reports
findings as either **errors** or **warnings**:

- **Errors stop startup.** They cover missing credentials, malformed base URLs,
  non-positive limits, prompt budgets below 1,000, and output caps above the
  documented maximum.
- **Warnings are logged and startup continues.** They cover values a provider
  may still accept, such as a non-`sk-` OpenAI-compatible key or a non-standard
  gateway URL.

Every error names the failing key and the accepted value or range. The module
does not certify a configuration beyond the constraints it can actually verify.
The live provider behaviour behind these checks is recorded in
[API-CONTRACT.md](API-CONTRACT.md).

## Errors That Abort Startup

- A missing `DISCORD_TOKEN`.
- A provider selected by its settings but missing its API key
  (`OPENAI_API_KEY` or `PERPLEXITY_API_KEY`).
- A configured provider whose key is missing (for example, its base URL or
  model was supplied without a key), or a Perplexity key that does not match the
  `pplx-` shape. A blank or whitespace-only key disables that provider; whitespace
  is stripped in both the config file and the environment.
- A base URL that is not an absolute `http(s)` URL with a host.
- `OUTPUT_TOKENS` or `PERPLEXITY_OUTPUT_TOKENS` that is non-positive or exceeds
  the fixed ceiling of **128,000**.
- A prompt budget that does not fit its context window: `INPUT_TOKENS` plus
  `OUTPUT_TOKENS` greater than `CONTEXT_WINDOW`, or the Perplexity equivalent
  using `PERPLEXITY_INPUT_TOKENS`, `PERPLEXITY_OUTPUT_TOKENS`, and
  `PERPLEXITY_CONTEXT_WINDOW`. The error names the keys and values.
- Non-positive `INPUT_TOKENS`, `PERPLEXITY_INPUT_TOKENS`, `CONTEXT_WINDOW`,
  `PERPLEXITY_CONTEXT_WINDOW`, `RATE_LIMIT`, or `RATE_LIMIT_PER` values, and
  non-positive `OPENAI_MAX_CONNECTIONS` or `PERPLEXITY_MAX_CONNECTIONS` values.
- `INPUT_TOKENS` or `PERPLEXITY_INPUT_TOKENS` below **1,000**. A malformed
  integer in `config.ini` or the environment is reported with a warning and its
  default applies instead; it does not abort startup.

## Warnings That Do Not Abort Startup

- An unknown `PERPLEXITY_MODEL`. The warning lists the known Agent API model
  set, currently `perplexity/sonar`. The provider may add models before this
  list is updated, so the name is not fatal; legacy Sonar names still answer on
  Chat Completions but warn here.
- An `OPENAI_API_KEY` that is non-empty but does not match OpenAI's `sk-`
  shape. Ollama Cloud and local gateways use their own formats, so this is a
  warning, never a fatal error.
- A well-formed base URL that is not one of the accepted endpoints (OpenAI,
  Ollama Cloud, or a local Ollama daemon). A compatible gateway may still work.
- A chat-provider `OUTPUT_TOKENS` value below **512**. `max_tokens` covers
  reasoning tokens as well as visible output, so
  a small cap can be spent entirely on reasoning. The API can then return HTTP
  200 with an empty message and `finish_reason: length`. Startup continues, but
  the warning explains why the value is risky.
- High token or rate limits that are legal but likely to increase usage or abuse.
- No configured channels.

## OpenAI-Compatible Provider

- The output cap is sent as `max_tokens` on Ollama-compatible hosts (`ollama.com`,
  `*.ollama.com`, `localhost`, `127.0.0.1`) and as `max_completion_tokens` on every
  other OpenAI-compatible host, including `api.openai.com`.
- `reasoning_effort` is sent from `REASONING_EFFORT` and is not validated
  against a local enum; valid values are model-defined.
- That cap covers **visible output plus reasoning tokens**.
- The fixed validation ceiling is **128,000** completion tokens, independent of
  `CONTEXT_WINDOW`. A larger value is an error; it is not silently clamped.
- Chat-generation-specific parameter validation does **not** exist in this codebase. The
  old check was removed, and this document no longer claims otherwise.
- Model names are not gated at all: any non-empty identifier is accepted.

## Perplexity

- The output cap is sent as `max_output_tokens` to the Agent API, which covers
  output only.
- The accepted range is **1..128,000**, the same fixed ceiling as the chat path and
  independent of `CONTEXT_WINDOW`. Values outside that range are errors.
- The current Agent API catalogue has one Sonar model, `perplexity/sonar`. A
  different name produces a warning that lists the known set; it does not
  prevent startup. Legacy names such as `sonar-pro` still answer on Chat
  Completions but are not the current catalogue.

## Discord

- `ACTIVITY_TYPE` and `BOT_PRESENCE` are checked against the enums exposed by
  discord.py.
- The client uses `discord.Intents.default()` with typing and presences
  disabled. That is a deliberate configuration choice, not a validation verdict
  for every deployment.

## Token and Rate Settings

```ini
[Default]
INPUT_TOKENS=250000
OUTPUT_TOKENS=16384               # chat provider max_tokens, includes reasoning
PERPLEXITY_OUTPUT_TOKENS=16384    # Perplexity max_output_tokens, output only
CONTEXT_WINDOW=1000000

[Limits]
RATE_LIMIT=10
RATE_LIMIT_PER=60
```

`PERPLEXITY_OUTPUT_TOKENS` is independent of `OUTPUT_TOKENS`. If it is omitted,
it defaults to the configured `OUTPUT_TOKENS` value, preserving older
configurations.
