# API Parameter Validation

## Overview

`src/api_validation.py` checks configuration before the bot starts. It reports
findings as either **errors** or **warnings**:

- **Errors stop startup.** They cover missing credentials, malformed base URLs,
  non-positive limits, and output caps above the documented maximum.
- **Warnings are logged and startup continues.** They cover values a provider
  may still accept, such as an unknown model name or a non-standard gateway URL.

Every error names the failing key and the accepted value or range. The module
does not certify a configuration beyond the constraints it can actually verify.
The live provider behaviour behind these checks is recorded in
[API-CONTRACT.md](API-CONTRACT.md).

## Errors That Abort Startup

- A missing `DISCORD_TOKEN`.
- A provider selected by its settings but missing its API key
  (`OPENAI_API_KEY` or `PERPLEXITY_API_KEY`).
- An API key that does not match the documented `sk-` or `pplx-` shape.
- A base URL that is not an absolute `http(s)` URL with a host.
- `OUTPUT_TOKENS` or `PERPLEXITY_OUTPUT_TOKENS` that is not an integer, is
  non-positive, or exceeds the documented maximum of **128,000**.
- Non-positive `INPUT_TOKENS`, `CONTEXT_WINDOW`, `RATE_LIMIT`, or
  `RATE_LIMIT_PER` values.

## Warnings That Do Not Abort Startup

- An unknown `PERPLEXITY_MODEL`. The warning lists the known set:
  `sonar`, `sonar-pro`, `sonar-deep-research`, `sonar-reasoning-pro`. The
  provider may add models before this list is updated, so the name is not fatal.
- An unknown `GPT_MODEL`. OpenAI accepts model names beyond any list shipped
  with the bot; only the shape is known locally, not the full catalogue.
- A well-formed base URL that is not the provider's documented endpoint. A
  compatible gateway may still work.
- An OpenAI `OUTPUT_TOKENS` value below **512**. OpenAI's
  `max_completion_tokens` covers reasoning tokens as well as visible output, so
  a small cap can be spent entirely on reasoning. The API can then return HTTP
  200 with an empty message and `finish_reason: length`. Startup continues, but
  the warning explains why the value is risky.
- High token or rate limits that are legal but likely to increase cost or abuse.
- No configured channels.

## OpenAI

- The output cap is sent as `max_completion_tokens`, not `max_tokens`.
- That cap covers **visible output plus reasoning tokens**.
- The documented maximum is **128,000** completion tokens. A larger value is an
  error; it is not silently clamped.
- GPT-generation-specific parameter validation does **not** exist in this codebase. The
  old check was removed, and this document no longer claims otherwise.
- Model names are not an allowlist gate. A name outside the documented list
  produces a warning because the provider may already support it.

## Perplexity

- The output cap is sent as `max_tokens`, which covers output only.
- The documented range is **1..128,000**. Values outside that range are errors.
- The documented model enum is `sonar`, `sonar-pro`, `sonar-deep-research`, and
  `sonar-reasoning-pro`. A different name produces a warning that lists the known
  set; it does not prevent startup.

## Discord

- `ACTIVITY_TYPE` and `BOT_PRESENCE` are checked against the enums exposed by
  discord.py.
- The client uses `discord.Intents.default()` with typing and presences
  disabled. That is a deliberate configuration choice, not a validation verdict
  for every deployment.

## Token and Rate Settings

```ini
[Default]
INPUT_TOKENS=120000
OUTPUT_TOKENS=8000                # OpenAI max_completion_tokens, includes reasoning
PERPLEXITY_OUTPUT_TOKENS=8000     # Perplexity max_tokens, output only
CONTEXT_WINDOW=128000

[Limits]
RATE_LIMIT=10
RATE_LIMIT_PER=60
```

`PERPLEXITY_OUTPUT_TOKENS` is independent of `OUTPUT_TOKENS`. If it is omitted,
it defaults to the configured `OUTPUT_TOKENS` value, preserving older
configurations.
