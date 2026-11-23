# Routing: design record

Status: the deterministic gate is the default production router; the optional Clef decision-model router
is implemented behind `ROUTER_MODE=clef`. This document describes what ships — what the decision is,
what decides it, what is deliberately absent, and what we know about its accuracy.

## The one question

> Does answering this message require live web data, or will the model's own knowledge do?

That is the whole job. It is not a probability, a score, or a confidence interval — it is a binary route
with a short, inspectable reason attached. Anything more is decoration.

## The decision, end to end

```
message ─▶ sanitize (Discord markup) ─▶ views (surface + folded NFKC/lowercase)
        ─▶ code-fence masking
        ─▶ extract cues:
             overrides      (explicit ask for web / a URL / explicit "from memory" / pasted artifact)
             structural     (status copulas, change verbs, versions, years, money shapes)
             lexicon        (volatile/commerce/incumbency/release terms — see src/routing/lexicon.py)
             follow-up      (short anaphoric continuations of the previous turn)
        ─▶ gate:
             web_instruction or URL        → web
             local_instruction / artifact   → local
             any surviving bearing cue      → web
             else, if a live follow-up      → inherit previous route
             else                           → local
```

Properties worth stating out loud:

- **Framing never decides.** Question marks, imperatives, register, names — none of it routes. A question
  about something static is `local`; "lol nice" is `local`; "thanks" is `local`.
- **The gate is one rule**: if the message refers to something whose answer changes (a price, a score, a
  version, who holds an office, whether it's down), it goes web. Otherwise it stays local.
- **No tuning surface.** No weights, thresholds, or per-channel variants exist. There is nothing to fiddle
  between deploys and nothing to drift.
- **Doubt goes local, then the safety net decides.** A local answer that the model itself flags as
  unverifiable ("I can't see live data…") triggers exactly one Perplexity retry with the original message.
  That — not the gate — is the answer to "how do we catch live questions phrased without any signal words?"

## What was deleted, and why it is not coming back

The previous implementation computed a weighted evidence score, squashed it through a sigmoid, and compared
it to a threshold (with a per-channel tau, an `unsure` band, a `tau_local` floor, per-family saturation, and
a `lambda_framing` multiplier). Measurement showed the score never changed a routing decision: the gate
"any bearing cue → web" produced **identical routes** on all 289 labelled rows at every threshold tested.
The sigmoid, the thresholds, the weights, and the `unsure` band are gone. Cache identity, telemetry, and
tests were updated to match.

What remains is what actually made decisions: the lexicon, the structural cue extractors, the maskers, and
the gate.

## Honesty section

- Measured on the two hand-labelled corpora in `tests/routing/corpora/` (blind-authored, ambiguous rows
  excluded): **0.728 recall / 0.716 precision / 0.779 accuracy**, identical row-for-row to the deleted
  scoring model. The corpora are committed as a regression fixture (`tests/routing/test_corpus.py`): they
  pin behaviour, they are not a benchmark, and they are not a target to tune against.
- Known miss class: live questions with **zero** signal words ("is it going to rain later?", "cheapest
  train friday?") route local. The safety-net retry exists for exactly this; it cannot fire if the model
  answers confidently from stale weights — that class is unrecoverable without an external signal or a
  model-in-the-loop decision, and we do not pretend otherwise.
- Known false-positive class: fluent pleasantries containing a volatile token ("the release notes said",
  "had the game last night" can trip release/outcome cues). Rare, bounded, cheaper than the alternative.
- Translation/i18n, multi-turn topic tracking beyond one gap, and per-server vocabularies: not supported,
  by decision.

## Invariants tests enforce

- Masked-vs-unmasked handling: no cue inside a code fence fires, whether an override, a version shape, a
  year, or a money/commerce term. Overrides and bearing cues both read the masked view.
- Inheritance only from a real previous assistant turn, at most one turn back, suppressed on topic shift.
- Corpus fixture: current behaviour matches the blessed confusion counts (any silent change fails CI).
- Determinism: same input, same route, every run, no clock/network/model dependence.

## Configuration

`ROUTER_MODE=heuristic` (default) is the deterministic gate. `ROUTER_MODE=clef` selects the optional
Clef decision-model router described below; `ROUTER_MODE=model` is retired and raises. All
`ROUTER_WEB_THRESHOLD_*` keys are gone; any lingering reference in an old config file is ignored
harmlessly (warned once at startup).

## The Clef decision-model router (optional)

`Router` is a protocol; `HeuristicRouter` and `ClefRouter` implement it. `ClefRouter` posts one bounded
request to Ollama Cloud at `/v1/systemone` with the last two prior turns (each capped at 600 characters)
and the current message as `state`. The single `needs_live_web` question is a `noul` probability;
`>= ROUTER_CLEF_THRESHOLD` routes web, otherwise local. A live probe measured roughly 0.35–0.43 s per
decision, billed per token; `ROUTER_CLEF_TIMEOUT_MS` defaults to 2 s and is enforced as a hard total
deadline for the asynchronous decision, not as a per-phase timeout.

A deterministic gate override is carried as data on the decision, and Clef returns that decision without a
network call. That includes a supplied artifact (`local:supplied_artifact`), so asking to summarize pasted
text cannot be flipped to web by Clef.

The Clef key is scoped to the Clef endpoint. Resolution order is `ROUTER_CLEF_API_KEY`, then
`OLLAMA_API_KEY` from the environment, then `OPENAI_API_KEY` only when `OPENAI_API_URL`'s host is
`ollama.com`. A key issued for any other chat provider is never sent to Ollama Cloud. When no eligible key
exists, startup warns once and selects the deterministic gate.

The router is built once at startup and reuses one pooled HTTP client for the process; the client is closed
with the other connection pools during shutdown. An image request is decided as `images:local` before any
router runs, so Clef is not consulted and the one routing log line is the decision actually used.

Any network error, timeout, HTTP status of 400 or above, or missing/malformed response logs a warning and
returns the deterministic gate's decision with a `clef:fallback:<kind>` reason. The gate therefore remains
both the default and the fallback; Clef never widens the routing surface or changes the prompt.

## Cache and identity

Responses are cached under `salt = "{route}:{router_id}:{policy_version}"` (`:reroute` for the safety-net
reply), combined with service/provider/source/degraded flags. Each decision carries its router identity:
the gate stamps `gate`/`1`, and Clef stamps `clef`/`1`, including its fallback decision. The orchestrator's
lexicon-error fallback keeps the gate defaults. A web answer and a local answer, or a gate answer and a
Clef answer, can never share an entry. Cache policy remains "cacheable unless URL-forced or the route was
local-with-bearing-cue", expressed at the call site — there is no router-emitted TTL object anymore.

## Failure modes

- Lexicon missing/corrupt at load → `LexiconError`; orchestrator falls back to a deterministic local
  decision with `reasons=("fallback:lexicon_error",)` and logs at CRITICAL. Bot keeps answering local.
- Router itself raising unexpectedly → caught at the decision site, local route, ERROR log.
- Empty/whitespace message → local, never an exception.

## Change log for this design

- 2026-10/11: initial weighted-scoring router (deleted 2026-11-14).
- 2026-11-14: scoring/sigmoid/thresholds/bands removed; deterministic gate; overrides on masked text
  (code-fence instructions no longer force web); web-inability reroute widened to any local route without
  an explicit local instruction; `ROUTER_WEB_THRESHOLD_*` removed; corpora promoted from "scoreboard" to
  regression fixture; behavior on both corpora row-identical pre/post change.
- 2026-11-15: optional Clef decision-model router added behind `ROUTER_MODE=clef`; the deterministic gate
  stays the default and the fallback on any Clef failure. `ROUTER_MODE=model` is retired and rejected at
  startup; use `heuristic` or `clef`.
