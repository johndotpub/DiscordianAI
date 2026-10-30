# Engineering Contract

This file is the contract for anyone — human or agent — changing this repository. It
complements `CONTRIBUTING.md`, which covers the community process. Where the two disagree
on engineering standards, this file wins. Every rule below is meant to be checked by a
command, a test, or a review diff.

## 1. What this is

DiscordianAI is a Discord bot that routes each incoming message to OpenAI or Perplexity,
keeps a per-conversation history, and renders the answer as Discord messages and embeds.
`src/message_router.py` decides whether a message is addressed to the bot;
`src/message_processor.py` normalises it; `src/smart_orchestrator.py` chooses the provider;
`src/openai_processing.py` and `src/perplexity_processing.py` call the providers; and
`src/message_splitter.py`/`src/discord_embeds.py` deliver the result. The module map is
`docs/Architecture.md`; the request/response contract with both providers is
`docs/API-CONTRACT.md`. Read both before changing a provider payload or a delivery path.

## 2. Invariants

These are not preferences. Each one exists because the previous version of this codebase
broke it, and each break is a user-visible bug.

- **One history writer.** Only `smart_orchestrator._record_conversation_turn()` may call
  `ConversationManager.add_message()`. `openai_processing.py` and
  `perplexity_processing.py` are I/O wrappers: they build a request, call the provider, and
  return normalised content/embeds. *Why:* an OpenAI answer that is rerouted to Perplexity
  must produce one turn, not two, and a failed attempt must produce none. *Consequence:*
  writing history inside a client duplicates or loses turns and corrupts follow-up routing.
  *Check:* `rg -n 'add_message' src` matches only `conversation_manager.py` (the definition)
  and `smart_orchestrator.py` (the call).

- **The orchestrator owns routing and its side effects.** `get_smart_response()` and its
  hybrid path build one `RouterInput`, call `router.decide()` once, pick the provider, fall
  back, and record the successful turn. No client module imports routing code or decides
  which provider runs. *Why:* routing is a single policy with one place to test.
  *Consequence:* duplicated routing drifts and produces answers from the wrong provider.
  *Check:* `rg -n 'build_router|build_router_input|\.decide\(' src` shows routing use only
  in `smart_orchestrator.py` and the `routing` package.

- **History is keyed per conversation, never per user.** The only valid keys are
  `g:<guild>:c:<channel>` and `dm:<user>`, built by
  `conversation_manager.make_conversation_key()`. A thread uses its own channel id, so a
  thread is not its parent channel. *Why:* one user can talk in a DM and in public
  channels; a per-user transcript replays private text into a public answer. *Consequence:*
  cross-channel and DM-to-guild leakage. *Check:* `tests/test_conversation_scope.py`,
  `tests/test_caching_scope.py`, and the key assertions in `tests/test_end_to_end.py`.
  The `user.id` fallback in `_record_conversation_turn()` exists only for legacy direct
  callers; production always passes `conversation_key`. Do not add another fallback.

- **The supervisor owns log output.** `main.setup_production_logging()` calls
  `structured_logging.configure_structlog()`, which clears the root logger and installs
  exactly one stream handler. `LOG_FILE` is parsed for backwards compatibility and ignored;
  it must not create a file. No module may add a second root handler or a `FileHandler`.
  *Why:* duplicate handlers duplicate every line, and a second sink makes rotation
  ambiguous. *Consequence:* duplicated logs and lost lines after rotation. *Check:*
  `tests/test_log_file_contract.py::test_configuration_keeps_exactly_one_root_handler` and
  `tests/test_structured_logging.py`.

- **One delivery helper owns the mention policy.** Every model-derived answer goes through
  `message_splitter.send_formatted_message()` and the private `_deliver()` it delegates to.
  `_deliver()` is the only place in `src/` that constructs `discord.AllowedMentions` or sets
  `mention_author=False`; no other module may call `Message.reply` for an answer. Fixed
  operational notices (rate-limit and error text) use `error_handling.safe_discord_send()`
  or the router's last-resort `channel.send`; they must stay constant text and must never
  carry model output. *Why:* an answer must not be able to mention `@everyone` or a role,
  and splitting must not create two mention policies. Pings are prevented both by the
  allowed-mentions policy (`everyone=False`, `roles=[]`) and by output neutralisation;
  delivery sets the policy explicitly. *Consequence:* mention abuse and inconsistent reply
  targeting. *Check:*
  `tests/test_delivery_helper.py::test_only_one_allowed_mentions_construction`,
  `tests/test_delivery_helper.py`, and `tests/test_golden_behaviour.py`.

- **The breaker wraps the retry.** Every chat-completion call goes through
  `get_circuit_breaker(provider).call(retry_with_backoff, ...)`. The breaker wraps the whole
  retry sequence, so three attempts for one logical call count as one failure
  (`DEFAULT_API_RETRY_CONFIG` currently allows two attempts). Never call
  `client.chat.completions.create()` directly from a new path. *Why:* retries are part of
  one user request, not separate failures. *Consequence:* one outage either trips the
  breaker several times too early or never trips it at all. *Check:*
  `tests/test_circuit_breaker_wiring.py`, especially
  `test_retries_inside_one_logical_call_count_as_one_failure`.

- **Prompt input is untrusted and bounded.** The current turn and history travel as
  role-tagged chat messages, never concatenated into the system prompt. Scraped page text is
  wrapped in `<untrusted_webpage_content>` with its delimiters escaped, and model output is
  sanitised before Discord. Every prompt is bounded by `INPUT_TOKENS`, `OUTPUT_TOKENS`, and
  `CONTEXT_WINDOW`; every scrape is bounded by `MAX_URLS_PER_MESSAGE`,
  `MAX_TOTAL_SCRAPED_CHARS`, and `SCRAPE_DEADLINE_SECONDS`. No new prompt may interpolate
  user or scraped text without both a delimiter and a size limit. *Why:* scraped pages can
  contain instructions, and unbounded text exhausts the context window. *Consequence:*
  prompt injection and truncated or failed requests. *Check:*
  `tests/test_untrusted_content.py`, `tests/test_token_budget.py`, and
  `tests/test_scrape_budget.py`.

- **Every user-supplied URL is checked on every hop.** `web_scraper.scrape_url_content()`
  calls `is_safe_url()` before the first request and re-resolves and re-checks every
  redirect `Location`, following at most three hops. Never fetch a URL that has not gone
  through that path. *Why:* the URL comes from a Discord message. *Consequence:* SSRF into
  loopback, RFC1918, link-local, CGNAT, or metadata endpoints. *Check:*
  `tests/test_scraper_ssrf.py` and `tests/test_web_scraper.py`. The HTTPS DNS-rebinding
  caveat is documented in `docs/Security.md`; do not claim protection the code does not
  have.

- **Config is additive.** A new key must default to the current behaviour when it is
  absent, and its default belongs in `src/config.py::_CONFIG_DEFAULTS`. Never rename or
  repurpose an existing key without a migration note in `CHANGELOG.md` and
  `docs/Configuration.md`. *Why:* existing `config.ini` files must keep working across an
  upgrade. *Consequence:* a silent behaviour change on deploy. *Check:*
  `tests/test_config_robustness.py`, `tests/test_single_source_defaults.py`, and
  `tests/test_docs_truth.py`. `ENTITY_DETECTION_MIN_WORDS` is parsed and documented but not
  wired into routing; do not treat it as a working tuning knob or add another key in that
  state.

## 3. Testing expectations

The suite is the specification. A reviewer should be able to check each rule below in the
diff or with the named command.

- **A bug fix ships with a test that fails without it.** The commit body must quote the
  failure (the assertion, traceback, or observed wrong output) so the next person can
  reproduce it. A fix without a regression test is not finished.
- **Mock at the boundary, never the function under test.** Fake the HTTP client and Discord
  objects; do not patch `get_smart_response`, the router, or the delivery helper when the
  test claims to verify routing or delivery. A test that still passes with
  the feature deleted is not a test. `tests/test_end_to_end.py` is the reference: only the
  Discord objects and `chat.completions.create` are faked.
- **Protocol boundaries are absolute numbers.** New tests state the regular-message limit
  as `2000`, the embed limit as `4096`, and the safe embed limit as `3840`; do not import the
  constant under test. `tests/test_message_splitting.py` and `tests/test_end_to_end.py`
  contain legacy imports of `MESSAGE_LIMIT`; do not add more.
- **No new wall-clock assertions.** Patch `time.monotonic` and `asyncio.sleep` (see
  `tests/test_retry_policy.py`) instead of sleeping or asserting elapsed time. The
  subprocess shutdown test and the fast-fail breaker test are deliberate exceptions because
  the bound itself is the behaviour under test. Do not leave unawaited tasks, and reset
  shared mutable state between tests (`tests/conftest.py` resets the provider breakers).
- **Shared fixtures live in `tests/conftest.py`.** A setup block copied three times is a
  defect. File-local fakes are fine when they are the boundary under test.
- **Coverage floor is 84% and must not fall in a PR.** The gate is `tox -e py312` or
  `python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=84`; plain
  `pytest` does not collect coverage. If deleting dead code lowers the percentage, say so
  in the PR and add coverage elsewhere rather than lowering the floor.
- **`tests/test_golden_behaviour.py` freezes delivery behaviour.** It must pass without
  regenerating fixtures. Regenerating `tests/fixtures/golden/*.json` is a deliberate
  behaviour change and needs its own justification in the commit/PR. Run
  `scripts/regen_golden.py` only for that purpose.
- **`tests/test_docs_truth.py` enforces documentation parity.** A doc change that trips it
  is either a doc bug or a genuine behaviour change that needs a CHANGELOG entry. Do not
  silence it by editing the test; use `docs/.doc-truth-allowlist.toml` only for a deliberate
  exception with a reason and a follow-up.
- **Five mutations must fail the suite.** The authorisation matrix and end-to-end test in
  `tests/test_message_router_auth.py` and `tests/test_end_to_end.py` exist to kill:
  inverting the channel-ID authorisation check; deleting the mention guard; disabling the
  ID allowlist branch; passing the Perplexity model name to the OpenAI client; and dropping
  the reply prefix. If one of those mutations starts passing, a test has been weakened.

## 4. Documentation standards

- **Docs describe behaviour, not intentions.** If a capability is not wired, it is not
  documented as a feature. Say "parsed but not used", as `docs/Configuration.md` does for
  `ENTITY_DETECTION_MIN_WORDS`.
- **Canonical config keys live in exactly three places:** `config.ini.example`,
  `src/config.py`, and `docs/Configuration.md` (including the complete example).
  Environment-only keys additionally belong in `.env.example` and the "Environment Variable
  Override" section. `tests/test_docs_truth.py` fails when those sets diverge. A deliberate
  exception goes in `docs/.doc-truth-allowlist.toml` with a `reason` and, where temporary, a
  `follow_up`.
- **Documented defaults and quoted constants equal the code.** Every `*(default: ...)*`
  and every `CONSTANT = value` line in prose is checked against `src/config.py`; change both
  sides in the same commit.
- **No references to deleted modules or functions, and no test-tree listings that enumerate
  files.** `tests/test_docs_truth.py` scans `README.md` and the top level of `docs/*.md` for missing modules,
  stale symbols, and non-existent commands.
- **When behaviour changes, the doc changes in the same commit.** A follow-up documentation
  PR is a broken contract, not a plan.
- **CHANGELOG.** Follow Keep a Changelog. Use the established section vocabulary:
  `### Behaviour changes` (user-facing sentences: what an operator or user will notice),
  `### Added ✨`, `### Fixed 🔧`, `### Changed 🔁`, `### Security 🛡️`,
  `### Documentation 📝`, `### Tests ✅`, `### Lint ✅`, `### Notes ⚠️`,
  `### Breaking Change ❗️🐍`, and `### Stats 📊`. `### Operations ⚙️` is also in use for
  deployment changes. The top released version must equal `pyproject.toml`
  (`tests/test_changelog.py`).

## 5. Code standards

- **Python 3.12.** `pyproject.toml` requires `>=3.12`, ruff targets `py312`, and CI tests
  3.12. Do not add compatibility shims for older interpreters.
- **Black and ruff are the formatters.** Black line length is 99; ruff selects the rule
  sets in `pyproject.toml`. `black . --check` and `ruff check .` must pass with no diff.
- **No new `noqa` without a reason on the line.** `# noqa: PLR0913` does not cover
  `PLR0917`; if a function has too many positional arguments, name both codes (as
  `src/message_splitter.py` does) and say why the signature is deliberate. The same applies
  to `# type: ignore` and `# pragma: no cover`.
- **Rule of three.** The third copy of a behaviour is a defect: extract it or table-drive it.
  Duplicated behaviour literals (model names, limits, retry counts) belong in
  `src/config.py` or the relevant module constant, not copied between modules.
- **No dead code.** Run `python -m vulture src --min-confidence 80` and then follow every
  hit through the call graph before deleting anything. Vulture reports cross-module
  constants as unused when scanning a single file: `python -m vulture src/config.py
  --min-confidence 60` calls `MESSAGE_LIMIT` unused even though `message_splitter.py` uses
  it. Check callers, not just the report.
- **Classify errors by type and status.** Use `error_handling.classify_error()` and the
  typed `ErrorType`/`ErrorSeverity` branches; do not match on a raw string when the
  exception type or HTTP status is available. A deterministic 4xx is not configurable and
  must not be reported as a transient provider failure.
- **Retry policy.** Retry failures a repeat can help: connection errors where no request
  was established, 429 with `Retry-After` honoured (capped at 30 seconds), and 5xx. Do not
  retry read timeouts, auth failures, validation errors, or other 4xx. Bound every retry
  with `RetryConfig.max_elapsed` (90 seconds by default). Do not add a retry to a path whose
  outcome is unknown. `docs/API-CONTRACT.md` records the provider idempotency caveat.
- **Annotate public functions.** Every public function and method has parameter and return
  annotations and a Google-style docstring. Frozen dataclasses are the default for request
  and config objects (`src/models.py`).
- **No blocking I/O in async paths.** Use `httpx`/`asyncio`; never `requests` or
  `time.sleep()` inside a coroutine. The same rule protects the Discord event loop.

## 6. Security rules

- **Never log or display a token, an API key, or a full request/response body.** Log counts,
  lengths, status codes, and classified error types instead. The debug line that dumps a
  discarded OpenAI answer in `_process_hybrid_mode()` is a known violation; shrink or remove
  it when you touch that path, and do not copy the pattern.
- **Treat model output as untrusted.** It goes through `sanitize_model_output()` and
  `sanitize_for_discord()`; it must not be able to create mentions, arbitrary markdown
  links, or embed payloads the bot did not construct.
- **Cap everything a user controls.** Message length is bounded by the prompt budget
  (`INPUT_TOKENS`/`CONTEXT_WINDOW`), URL count by `MAX_URLS_PER_MESSAGE`, scraped text by
  `MAX_TOTAL_SCRAPED_CHARS`, scrape time by `SCRAPE_DEADLINE_SECONDS`, and request rate by
  `RATE_LIMIT`/`RATE_LIMIT_PER`. New user-controlled input needs an explicit cap.
- **Validate redirects.** `is_safe_url()` must run on the initial URL and on every redirect
  target; the client uses `follow_redirects=False`. The maximum chain is three hops.
- **State the residual gap.** HTTPS connections keep the hostname for TLS and therefore
  cannot be pinned to the vetted IP; a DNS-rebinding window remains and is documented in
  `docs/Security.md`. Prompt delimiters reduce injection risk but do not make a model obey
  them. `/health` reports observed provider state, not a live probe before the first call.
  Do not claim a protection the code does not implement.

## 7. Commit and PR rules

- **Subject:** `type(scope): <emoji> subject`, at most 72 characters, exactly one emoji.
  Use the prefixes already in the history: `feat`, `fix`, `refactor`, `test`, `docs`,
  `build`, `chore`, `ci`.
- **Body:** wrap at 72 columns. Say what was wrong, why it mattered, and which test prevents
  it from coming back. Do not put finding IDs, review-round counts, or "address review
  comments" in public text; describe the defect and the fix instead.
- **Stage explicit paths:** `git add <paths>`. Never `git add -A`; the tree contains
  generated caches and artefacts.
- **Do not force-push after review opens.** Add a new commit; do not rewrite reviewed
  history.
- **Keep refactors separate from fixes.** A rename/move commit and a behaviour-change commit
  are reviewed differently; do not hide one inside the other.
- **Write the message to a file and commit with `-F`:** `git commit -F /tmp/commit-msg`.
  This keeps the 72-column body intact and makes the message reviewable before commit.

## 8. Verification before you push

Activate the project virtual environment first (`source .venv/bin/activate` in this
checkout; use your own venv path otherwise), then run every gate. The wrapper runs the same
checks in order and stops at the first failure.

```bash
source .venv/bin/activate
bash scripts/preflight.sh

black . --check
ruff check .
python -m pytest
python -m sphinx -b html docs/api docs/api/_build -W
pip wheel . -w /tmp/wheels --no-deps
# If the PyPA build frontend is installed and the local build/ directory is
# not shadowing it: python -m build --wheel
```

Coverage is a separate gate because plain `pytest` does not collect it:

```bash
python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=84
# equivalent canonical CI runner:
tox -e py312
```

## 9. Operations

- **Clean shutdown.** `SIGTERM` and `SIGINT` set one shutdown request and schedule one task.
  `DiscordBotManager.SHUTDOWN_TIMEOUT` is 8 seconds; a hung close logs the timeout, flushes
  stdout/stderr, and exits 0. A second signal does not run shutdown again. Check:
  `tests/test_shutdown_signals.py`.
- **`/health` reports observed provider state.** It returns 200 only when the bot is ready,
  at least one provider client exists, and no provider is degraded or unhealthy; otherwise
  503. `/health/live` reports process liveness; `/health/ready` adds the Discord connection
  and provider health. A configured client that has never been called and has no recorded
  failure still reads healthy: this is observed state, not an active probe. Check:
  `tests/test_health_truth.py`.
- **A health-server bind failure must not kill the bot.** `HealthServer.start()` catches the
  bind/startup failure, logs once, disables the endpoint, and leaves the Discord client
  running. Check:
  `tests/test_health_truth.py::test_bind_failure_disables_health_server_without_killing_bot`.
- **One instance per token.** A Discord token cannot have two live gateway sessions without
  duplicate replies. `discordian.sh` enforces this for launches it owns through `.bot.pid`;
  containers, systemd, and other supervisors must enforce the same rule externally. The
  Python process itself does not lock the token.
- **Log rotation uses the shipped fragment.** `contrib/logrotate/discordianai` rotates a
  supervisor-owned `bot.log` with `copytruncate`, because the bot does not reopen a log file
  it never opened. Install it and replace the placeholder path.
- **The supervisor owns stderr.** Logs go to stderr (`LOG_FILE` is ignored). The shipped
  systemd unit appends stdout/stderr to `bot.log`; Docker captures both streams. Use one
  owner for redirection so lines are neither duplicated nor lost.
- **Keep the health endpoint local by default.** `HEALTH_HOST` defaults to `127.0.0.1`.
  The compose file sets `0.0.0.0` inside the container but publishes only
  `127.0.0.1:8080` on the host.

## 10. Failure modes learned here

These cost real debugging time in this repository. Recognise them before repeating them.

- **The discord.py loop sentinel.** `bot.loop` is a sentinel, not a running loop, until
  discord.py is inside its own loop. Reading it from a signal handler raised
  `AttributeError`, so shutdown never ran. Capture the loop from `setup_hook`/`on_ready`
  and hand work to it with `call_soon_threadsafe`; never call `asyncio.run()` from a signal
  handler.
- **`noqa: PLR0913` does not cover `PLR0917`.** Suppressing the too-many-arguments warning
  left the too-many-positional-arguments warning live, and CI failed after the local check
  appeared clean. Name both codes and justify the signature.
- **A wheel can install flat.** An editable install and a test run from the checkout hid
  the fact that setuptools auto-discovery shipped every `src/*.py` as a top-level module,
  so `discordianai = "src.main:main"` could not import `src`. `packages = ["src"]` and
  `package-dir = {"" = "."}` fix it; the wheel smoke test in `.github/workflows/ci.yml`
  proves the wheel contains `src/` and no top-level modules.
- **A test can mock the exact attribute that is broken.** The health pool test asserted a
  mocked `http2_enabled` value while the real client read an attribute httpx does not have,
  so the endpoint always said false. Assert against the real client configuration, as
  `tests/test_health_truth.py::test_http2_enabled_reflects_the_client_configuration` does.
- **Coverage can stay green while one user's answer is served to another.** The cache key
  once omitted the requester and the conversation; the same words from two people returned
  one person's answer. Cache and dedup keys are scoped to the conversation key plus a
  digest of the conversation, with the requester as a fallback when no conversation key is
  given; `tests/test_caching_scope.py` is the guard.
- **A config key can be parsed, validated, and read by nothing.** `LOG_FILE` is deliberately
  ignored (and documented as such); `ENTITY_DETECTION_MIN_WORDS` is parsed but not wired
  into routing. A new key that nothing reads is a lie in `config.ini.example`; wire it, or
  document that it is inert, or delete it.
