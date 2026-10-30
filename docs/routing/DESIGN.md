# Routing: design record

Status: accepted design, implementation in progress. Supersedes the regex chain in
`src/smart_orchestrator.py`.

Scope decisions taken with the project owner:

- **English only.** No language switch, no per-language data, no start-up refusal for other scripts. One
  lexicon, tuned for English; other input routes as best it can.
- **No cost cap, no budget logic.** Routing decides on the message's need for live data, not on spend.
  There is no token bucket, no forced-local-on-budget, no price model in the router.
- **No per-guild lexicon overrides.** One lexicon ships with the release; operators do not extend it at
  runtime.
- **Outright replacement.** This replaces the regex router in one step — no shadow mode, no A/B arms, no
  percentage ramp, no canary guild. The old path is deleted, and reverting means reverting the commit.


## Why

Routing decides whether a message is answered by a local model or by a web-searching one. The current
implementation is an ordered chain of ~52 regexes with ~275 literal alternatives, and it measures 66%
accuracy on an independently authored 74-message corpus — 21 live questions missed, 4 needless searches.
Its failures are structural, not a matter of a longer word list:

- Branch order is the classifier. A greeting returns before the live-data check, so
  *"Hi there, what's the latest news?"* is answered locally.
- Two implementations of one decision: `_identify_routing_triggers` re-runs the same regexes to write a
  log line, so the log can contradict the decision.
- Vocabulary as code: adding `restock` needs a release, a doc edit and a fixture regeneration.

The goal is a router that does not need continual vocabulary maintenance, is complete on its own with no
model and no network, and can later be replaced by a decision model without refactoring its callers.

## The idea

> A message needs the live web when it refers to something whose value can change, and the answer is
> expected to be verifiable.

Two evidence classes follow, and the split is what makes it general:

- **Bearing** — a mutable referent: a status predicate, a change or outcome event, a price or quantity
  shape, a version shape, a volatile topic noun. Bearing may decide.
- **Framing** — the shape of the request: question, imperative, opinion, creative, social, greeting,
  presence of a proper name. Framing is multiplied by `lambda_framing < 1` and **can never decide alone**.

Four known failures fall out of this for free:

| Failure | Why it disappears |
|---|---|
| `what is X` routes to web, `what's X` does not | Contraction folding happens before frame detection; both fold to `what is` |
| `Thank You`, `Best Regards` route to web | Social register is framing with negative weight, not a positive entity signal |
| `find the bug in this loop` routes to web | The deictic object (`this loop`) marks the task as local, and search intent loses to it |
| `main.py`, `asyncio.gather` route to web | Filenames are masked before URL detection; the URL test requires a public suffix |

## Contract

```python
# src/routing/contracts.py
Route = Literal["web", "local"]
Band = Literal["confident", "unsure"]
EvidenceClass = Literal["override", "bearing", "framing", "local"]

@dataclass(frozen=True, slots=True)
class Evidence:
    signal: str                    # "pred.status", "time.deixis", "override.url"
    klass: EvidenceClass
    weight: float                  # already applied; signed
    span: tuple[int, int] | None   # offsets into the original text
    detail: str                    # "sold out", "v3.12.0", matched term
    source: Source = "structural"

@dataclass(frozen=True, slots=True)
class CachePolicy:
    cacheable: bool
    ttl_seconds: int
    salt: str                      # f"{route}:{router_id}:{policy_version}"

@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: Route
    band: Band
    confidence: float
    score: float
    evidence: tuple[Evidence, ...]
    cache: CachePolicy
    router_id: str                 # "heuristic@1" | "clef@<digest>"
    policy_version: str
    latency_ms: float

class Router(Protocol):
    router_id: str
    policy_version: str
    async def decide(self, request: RouterInput) -> RouteDecision: ...
```

**The trace is the decision.** `score == sum(e.weight for e in decision.evidence)` is a tested invariant.
`_identify_routing_triggers` is deleted, not deprecated: a reason can only appear in the log if it moved
the number.

`decide` is async even though the heuristic does no I/O, so a model implementation is a swap rather than a
refactor. `HeuristicRouter` additionally exposes `decide_sync` for tests and the evaluation harness; the
model deliberately does not, so nothing can come to depend on a synchronously available model.

## Heuristic: fixed pipeline, no early returns

```
views    = features.views(text)          # surface (case kept) + folded (NFKC, apostrophes, lowercase)
overrides= features.overrides(views)     # url, "search the web", "from memory"
cues     = features.extract(views)       # unweighted bearing + framing cues
score    = sum(bearing) + lambda_framing * sum(framing)
p_web    = sigmoid((score - t_mid) / temperature)
route    = web     if p_web >= tau
           local   if p_web <= tau_local
           unsure  otherwise            # local + optional deferred recheck
if no bearing cue and no override: route = local      # a rule, not a threshold
```

The gate is load-bearing: **no bearing cue means no web route**, however question-shaped the text.
Symmetrically, `lambda_framing * max_positive_framing < tau` is asserted, so no future tweak can let
framing decide alone. Each family saturates (best hit full weight, second half, rest ignored) so
`latest current news today` cannot stack to certainty.

### Bearing families (structural shapes and predicates, not topic lists)

`pred.status` (copula within 3 tokens of a state adjective), `pred.change` (changed, released, shipped,
went live, launched, rolled out, dropped, announced), `pred.outcome` (won, lost, beat, elected, passed),
`pred.event` (what happened, any updates, what's new), `pred.compat` (works with, supports),
`pred.release` (out yet, release candidate, early access, deprecated), `shape.version` /
`shape.version_range`, `shape.money` / `shape.unit`, `time.year` (year >= current year − 1, from an
injected clock — never a literal list), `topic.volatile` (weather, news, rate, score, schedule, outage,
advisory, hours, flight), `topic.commerce` (price, cost, fare, a month, in stock, sold out),
`topic.incumbency` (president, ceo, manager, these days), `topic.version_currency` (version, lts, kernel,
release notes, roadmap), `time.deixis` (closed-class; bearing **only when another bearing cue exists**,
otherwise weak framing — this is the fix for *"I spoke to John Smith yesterday"*).

A bare `change` or `changes` is not a `pred.change` event: the class requires a change of state about a
thing. A counted duration (`two hours`, `3 hours`) is not an opening-hours `topic.volatile` cue. A
declarative role mention (`the president of the company`) does not become `topic.incumbency` without a
question or another bearing cue.

### Framing families

`frame.question`, `frame.imperative`, `frame.opinion`, `frame.creative`, `frame.procedural`,
`frame.social_only`, `frame.greeting` (weight 0: logged, never decisive), `frame.bounded_relation`
(`capital of`), `frame.open_reference` (`tell me about`), `ref.entity` (title-case run; **always framing**),
`neg.narrative` (first person + past + deixis), `neg.env` (my server / repo / branch / code),
`neg.supplied_artifact` (a pasted log, diff, note, JSON, paragraph, or quoted block that the user asks to
summarise, explain, or transform; this cancels `topic.volatile` and `pred.change` in the same message),
`code.shape` (fenced block, traceback, masked filename), `cue.lookup` (decides upward but loses to code
context).

### Normalisation

Two parallel views over identical offsets: `surface` (case preserved — entity detection, log spans) and
`folded` (NFKC, unified apostrophes, lowercased). Never lowercase before entity detection; never send
`folded` to an API.

- Contraction folding from a closed ~25-entry table (`what's` → `what is`). This is the `what is X` /
  `what's X` fix.
- Filenames masked before URL and entity detection.
- URL detection requires a public-suffix label and rejects masked filenames, so `asyncio.gather` and
  `package.json` are not URLs.
- Typos without a misspelling list: a delete-1 index over lexicon terms (SymSpell shape), built at load;
  a token within edit distance 1 hits its class. `wether`, `githbu` match. Present-tense forms such as
  `change` and `changes` never inherit a past-tense class term.

### Explicit control prefixes

`features.parse_explicit_route()` runs before scoring and is O(1) on the first token. `!web`/`?web` force
web, `!local` forces local, and `?status`/`?price`/`?release`/`?news` force web while recording the named
class as an override witness. The token must be lowercase at position zero and followed by whitespace;
anything else is ordinary text. The decision carries `source="override"` and the remainder in
`RouteDecision.text`, and it is never cacheable under the plain message's salt.

### Inheritance

A follow-up is ≤ 6 tokens **and** (closed-class anaphor, bare continuation, or leading coordinator)
**and** an assistant turn at gap ≤ 1. Then `last_route` applies at +2/−2. Escape hatches: any bearing cue
wins; a title-case token or content word absent from prior user terms cancels (topic shift); gap decay
stops *"the second one?"* inheriting two turns later.

## Lexicon: data, not code

`src/routing/data/lexicon.en.json`, class weights rather than term weights:

```json
{"version": "1", "language": "en",
 "classes": {
   "state_adjective": {"klass": "bearing", "weight": 2.4, "terms": ["down", "offline", "busy", "available"]},
   "release_state":   {"klass": "bearing", "weight": 2.2, "terms": ["out yet", "release candidate", "early access", "deprecated"]},
   "commerce":        {"klass": "bearing", "weight": 2.0, "terms": ["how much", "price", "cost", "a month", "in stock", "sold out"]},
   "incumbency":      {"klass": "bearing", "weight": 1.6, "terms": ["president", "ceo", "manager", "these days"]},
   "version_currency":{"klass": "bearing", "weight": 1.8, "terms": ["version", "lts", "release", "changelog", "roadmap"]},
   "volatile_topic":  {"klass": "bearing", "weight": 1.8, "terms": ["weather", "news", "score", "outage", "advisory", "hours", "flight"]},
   "social_only":     {"klass": "framing", "weight": -4.0, "terms": ["thanks", "best regards", "goodnight"]}
 },
 "overrides": {"web_instruction": ["search-or-browse within 20 chars of web/internet/online"],
               "local_instruction": ["from memory", "do not search"]}}
```

Adding a term is one JSON line, no release and no tuning. Load-time validation fails startup naming the
key: unknown class, weight outside [−10, 10], a term in two classes, an uncompilable regex, a version
mismatch.

One global lexicon ships with the release. There is no operator overlay and no per-guild extension: the
    bundled file is the whole vocabulary, and changing it is a release.

## Caching

The router emits its cache policy; the caller obeys it. `_generate_scoped_key(message, context, *, salt)`
becomes keyword-only with **no default**, so a call site cannot forget it.

- `cacheable` is false for the unsure band, for a local route that carried bearing cues, and for URL
  overrides.
- Response-cache key gains `service`, `router_version`, `decision_source`, `function` and `degraded`.
  Today it drops all five, which is how a web-routed message was served a cached OpenAI answer.
- A degraded fallback (web failed, local answer returned) is stored with `degraded=true` and replayed only
  as a failure, never as a web answer.
- Perplexity answers are cached for at most 120 s, because they carry citations and go stale.

## Observability

One structured line per decision, content-free: `ts, evt=route, req_id, guild_hash, channel_hash,
conv_hash, service, score, threshold, source, reasons (≤5 feature ids), rules_version, config_fp,
latency_us`.

Three log statements currently leak message content and are removed: the sanitised message in
`smart_orchestrator`, the raw message, and `entity:<matched text>`.

Counters survive restarts (absolute totals, hourly flush and on SIGTERM, boot id gap on crash) and surface
in `/health` as a `router` block: web share, false-local count, fallback count, rules_version.

## Rollout

This is a replacement, not a migration with arms. The new router is wired in, the old chain is deleted in
the same release, and there is no shadow mode, no percentage ramp and no canary guild.

The only runtime switch is `ROUTER_MODE=heuristic|model`, which selects the implementation and defaults to
`heuristic`. Per-channel-kind thresholds (`ROUTER_WEB_THRESHOLD_CHANNEL` 0.10,
`ROUTER_WEB_THRESHOLD_ANNOUNCE` 0.07, `ROUTER_WEB_THRESHOLD_DM` 0.20) are tuning, not rollout: they exist
because a public channel and a DM have different costs of being wrong, not to stage the change.

Reverting means reverting the commit — the old router is gone rather than dormant, which is why the
evaluation floors below are a release gate rather than a monitoring exercise.

## Evaluation

`scripts/router_eval.py --corpus FILE [--json] [--baseline old|none] [--slice FIELD]` scores JSONL
rows with `text`, `expect` (`web`, `local`, `ambiguous`), optional `slice` and `why`. It excludes
ambiguous rows, reports recall first with a 95% Wilson interval, and prints the overall and per-slice
confusion matrix. `--baseline old` scores the incumbent `should_use_web_search()` on the same rows and
prints the delta; `--json` is the CI form.

Floors are **per slice**, because the two error directions cost differently: a missed live question is a
confidently stale answer (5–10× worse), while a needless search on *"thanks, that was lovely"* is a public
embarrassment that a technical false positive is not.

| Slice | Recall (needs live) | Precision |
|---|---|---|
| Social / chat | — | ≥ 0.98 |
| Technical / code | — | ≥ 0.60 |
| Overall | ≥ 0.90 (target 0.92) | ≥ 0.75 |

Plus: hard-rule cases exact (URL, explicit search, creative-only); two runs identical and hermetic
(sockets blocked); 20 labels flipped with a fixed seed must fail the suite; every production misroute gets
a corpus row before it is fixed.

## Clef seam

`ROUTER_MODE=model` selects `src/routing/clef.py`, which implements the same `Router` protocol over
Ollama's `/v1/systemone` with typed questions (`needs_live_data` as a `noul`, `confidence` as a `score`).
Constraints that keep it optional:

- Never on the default path; no import of the client unless selected.
- Consulted only when the heuristic score sits inside `ROUTER_MODEL_BAND` of the threshold, with a hard
  `asyncio.wait_for(ROUTER_MODEL_TIMEOUT_MS)`; on timeout, error or absence, the heuristic answer stands
  with `source="heuristic_fallback"`.
- Same cache policy and the same conformance suite; it must beat the heuristic's corpus accuracy by a
  configured margin before it may become the default, and that change is its own revertable commit.
- `/health` reports fallback rate and p95 model latency, so "enabled but always timing out" cannot go
  unnoticed.

## Migration

| Step | Change | Behaviour |
|---|---|---|
| 1 | `src/routing/` contracts, features, scoring, heuristic, lexicon + unit tests | none (not wired) |
| 2 | Wire the router in; delete `_identify_routing_triggers`; fix the cache key, the double Perplexity attempt, the manager-None crash | intended |
| 3 | Delete the old pattern lists and the truth-test entries they dragged in; docs | none |
| 4 | Optional model behind `ROUTER_MODE` | none when off |

Step 1 is behaviour-preserving by construction because nothing calls it. Step 2 is the replacement, and it
carries the evaluation gate: the corpus floors are checked before the commit that wires it in, not after.
There is no parity stage — comparing two routers side by side is the shadow mode this design does not
have.
