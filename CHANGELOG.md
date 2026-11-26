# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Behaviour changes

- **Non-positive connection limits stop startup.** `OPENAI_MAX_CONNECTIONS` or
  `PERPLEXITY_MAX_CONNECTIONS` set to 0 or a negative value now fails validation with an
  ERROR naming the key, because every request would otherwise wait out the pool timeout.
  Non-positive `MAX_HISTORY_PER_USER`, `CONVERSATION_TTL_SECONDS`, and
  `USER_LOCK_CLEANUP_INTERVAL` keep their existing runtime behaviour and log one warning
  each instead of aborting.
- **Prompt estimates follow the script.** ASCII prose and code keep the historical
  one-quarter token per character. Characters from U+0080-U+07FF cost one-half token,
  U+0800-U+FFFF cost 0.8, and astral-plane characters (most emoji) cost 1.7, all before
  the existing 1.1 margin and per-message overhead. A Chinese, Japanese, Korean, Hindi, or
  emoji history is therefore no longer estimated at the ASCII rate, so the Perplexity
  prompt stays inside its 128K window instead of silently exceeding it.
- **A context window smaller than its budgets stops startup.** `INPUT_TOKENS` plus
  `OUTPUT_TOKENS` must fit `CONTEXT_WINDOW`, and the Perplexity trio must fit
  `PERPLEXITY_CONTEXT_WINDOW` using the same effective values the request builder uses.
  A configuration such as `CONTEXT_WINDOW=2000` with the default 250,000-token prompt
  budget now fails with an ERROR naming the keys instead of cutting every question to a
  fragment.
- **Oversized answers are bounded before delivery scans them.** An answer longer than
  `MAX_SPLIT_CHUNKS` times `MESSAGE_LIMIT` (100,000 characters with the defaults) is
  truncated with the existing chunk-cap notice and ERROR log line before sanitisation or
  splitting. Long code-heavy answers no longer stall the Discord event loop while every
  chunk reparses the remaining text.
- **Startup provider checks use the same bounded probe as the adapters.** The
  reachability check now times out instead of waiting indefinitely, and the
  in-process check counters and recent-result list that nothing read are gone.
  `/health` still reports observed breaker state rather than running a live probe.
- **A routing lexicon may still carry a per-class weight field.** The field is
  ignored when the lexicon loads, so an existing data file keeps working while the
  removed scoring layer stays removed.
- **The channel rate-limit notice uses the standard message.** A rate-limited
  channel reply now asks the user to wait before sending another message, matching
  the direct-message notice, instead of using a second hand-written copy.
- **The launcher keeps one instance per config.** The restart loop no longer exits the
  script on its first second under `set -e`, and each config now records its PID in
  `.bot-<stem>-<hash>.pid`, where the hash comes from the resolved absolute config path.
  Starting `production.ini` leaves a running `bot.ini` alone, and two configs that share a
  basename in different directories no longer share one PID file. The straggler scan reads
  the NUL-separated argv, so a checkout path containing a space still matches, and compares
  the absolute config path, so two checkouts that both use `bot.ini` no longer match each
  other. A legacy `.bot.pid` is honoured only when its process runs the same config. The
  force-kill wait is overridable with `DISCORDIANAI_STOP_TIMEOUT` for tests and unusual
  supervisors. `--install-systemd` now starts the unit after enabling it.
- **A stale launcher PID file cannot signal an unrelated process.** The per-config PID
  file is trusted only when its process still runs the same config. A number left by a
  reboot is removed without a signal, so the next restart cannot kill an unrelated process.
- **`LOG_FILE` is mentioned only when it is actually set.** The deprecated key has a
  built-in default, so every startup used to log an "ignored" notice while directing
  operators to stdout even though logs go to stderr. The notice now appears only when the
  environment or `[Logging]` section sets the key, and it names stderr.
- **An empty setting means "not set".** Blank `GPT_MODEL`, `PERPLEXITY_MODEL`,
  `OPENAI_API_URL`, `PERPLEXITY_API_URL`, and the other string settings now fall back to
  their documented defaults instead of reaching the provider as empty strings. A blank
  environment override is treated the same way and no longer marks its provider as
  explicitly selected. A blank `REASONING_EFFORT` omits the parameter, and a blank API key
  still disables its provider.
- **Config values are literal, and a bad config file stops startup.** A `%` in a prompt or
  secret (for example `SYSTEM_MESSAGE=I am 100% sure`) no longer breaks parsing, and `%%` is
  kept as two characters instead of being collapsed. A missing, unreadable, duplicated, or
  malformed `--conf` file now stops startup with the file path, the error class, and any
  source line numbers, without quoting the offending line or chaining the parser exception.
  Files are read as UTF-8 and a decode error is fatal.
- **Perplexity prompts fit the Sonar context window.** The web path now budgets prompts with
  `PERPLEXITY_INPUT_TOKENS` and `PERPLEXITY_CONTEXT_WINDOW` (111,000 and 128,000 by default)
  instead of the chat provider's 250,000 and 1,000,000. The fixed `fetch_url` instruction
  suffix is charged against the prompt budget before history is trimmed, so a full prompt
  plus `PERPLEXITY_OUTPUT_TOKENS` stays inside the 128K window taken from the former Sonar
  model page (the Agent API models page publishes no context figure). Both Perplexity
  limits must be positive integers like the shared limits, and an operator who lowers
  `INPUT_TOKENS` or `CONTEXT_WINDOW` still caps the Perplexity prompt with the smaller
  value. `INPUT_TOKENS` and `PERPLEXITY_INPUT_TOKENS` also share a 1,000-token minimum, so a
  budget that would cut a real question to a fragment is rejected at startup.
- **Pasted code and logs stay local.** A version string, current year, price, or other bearing cue inside
  a fenced code block no longer routes the message to web search; bearing and override cues are extracted
  from the code-masked view, and text outside the fence still counts as before. Code-shape and traceback
  cues still read the original text so a pasted artifact is marked as code-shaped, but they are framing
  cues and cannot decide a route alone.
- **Image requests decide before the router runs.** An image-bearing message uses the `images:local`
  decision without consulting Clef, and the single routing log line reports that decision.
- **Clef is consulted only when it can act, under one deadline.** A deterministic gate override such as a
  supplied artifact is returned without a Clef call, the router is built once and reuses a pooled client,
  and `ROUTER_CLEF_TIMEOUT_MS` is a hard total deadline for one decision.
- **A missing or corrupt routing lexicon no longer stops startup.** `build_router` logs it
  at CRITICAL and injects a local-only fallback router, so the bot keeps answering on the
  local route instead of aborting before it connects.
- **Router faults fall back to the deterministic gate.** An unexpected router failure or a Clef error logs
  a reason and continues through the gate instead of turning every hybrid message into an error reply.
  An unknown `ROUTER_MODE` now fails startup validation; `model` keeps its explicit retirement error.
- **The web-inability reroute requires a first-person admission.** General statements, quoted text, and
  creative output such as a haiku mentioning browsing no longer discard a good local answer.
  Typographic apostrophes are normalised before matching, so an answer such as "I’m unable
  to browse the internet" still triggers the one Perplexity retry.
- **Shutdown closes provider resources before Discord.** Message intake stops first, then
  the provider connection pools and the router's HTTP client close, and Discord closes
  last inside the existing 8-second guard. Closing Discord first let `Client.run` finish
  and cancel the rest of shutdown, leaking those HTTP connections on a normal stop. Any
  exception raised during shutdown is logged and the process still exits 0.
- **Configuration errors make a provider unhealthy; a user's bad request does not.**
  A 401, 403, or 404 now counts as a provider failure, and so does a 400 whose structured
  error names the model: type or code `invalid_model` or `model_not_found`, `param` equal to
  `model`, or a message that combines `model` with `is not supported`, `not found`, or
  `does not exist`. This covers the recorded Agent API response, whose inner error says
  `validation failed: model "sonar" is not supported`. A revoked key or a retired model
  therefore shows up as degraded or unhealthy on `/health` instead of looking healthy while
  every call fails. A 400, 409, 413, 422, or other user-caused client error
  stays neutral: it releases a half-open probe without stamping a success or moving any
  counter.
- **Startup reachability checks log one line per provider.** Each checked service
  reports its status, latency, and classified error type; provider text, request
  and response bodies, and keys are not logged.
- **Ollama Cloud is the default OpenAI-compatible chat provider.** `OPENAI_API_URL` defaults to
  `https://ollama.com/v1/` and `GPT_MODEL` defaults to `deepseek-v4.1-flash:1017`. OpenAI remains
  supported by changing `OPENAI_API_URL`, `GPT_MODEL`, and `OPENAI_API_KEY`; the Perplexity path is
  unchanged.
- **Chat requests choose the output-cap parameter by provider.** Ollama-compatible hosts
  (`ollama.com`, `localhost`, `127.0.0.1`) receive `max_tokens`; `api.openai.com` receives
  `max_completion_tokens`. The cap still includes reasoning tokens as well as visible output.
- **Provider model ids are no longer gated.** Any non-empty `GPT_MODEL` is accepted, and the health
  check no longer reports a non-empty model as deprecated or unsupported.
- **An `OPENAI_API_KEY` that is not `sk-`-shaped is no longer fatal.** Empty keys still fail; a
  non-OpenAI-compatible key shape logs a warning so Ollama Cloud and local gateways work.
- **Empty chat responses log the finish reason.** The client warns with `finish_reason` and returns
  no content, so the orchestrator's existing fallback handles it instead of delivering empty text.
- **Routing is a deterministic gate; the scoring layer is gone.** A message routes to the web when an
  explicit web instruction, URL, or bearing cue survives the existing gates, inherits the prior route
  on a follow-up, and otherwise stays local. The channel-kind probability thresholds
  (`ROUTER_WEB_THRESHOLD_CHANNEL`, `ROUTER_WEB_THRESHOLD_ANNOUNCE`, `ROUTER_WEB_THRESHOLD_DM`) are
  removed; an existing `config.ini` that still sets them loads without error and ignores them.
- **Clef answers carry Clef's own cache identity.** The selected router's `router_id` and
  `policy_version` now stamp the cache salt, so a Clef answer uses `{route}:clef:1` instead of the
  gate's `{route}:gate:1` and the two cannot share an entry. The deterministic gate keeps its
  existing identity.
- **Web-tool inputs are bounded.** A `web_search` query longer than 500 characters or a `web_fetch`
  URL longer than 2,048 characters becomes an error tool result instead of a provider request;
  `max_results` stays clamped to 1–10. Tool debug logs record only the tool name and argument byte
  length, never the query or URL.
- **Perplexity answers use the same response cache as chat answers.** An identical Perplexity
  request in the same conversation and routing scope now returns the cached answer for the cache
  TTL instead of calling the provider again. The key includes the model, system message, history,
  conversation scope, routing salt, and degraded flag, so a cached answer is never replayed across
  conversations or routes.
- **The response cache has one TTL, and time-sensitive wording is found anywhere.** Every
  cached answer uses the fixed `DEFAULT_CACHE_TTL` of 600 seconds; the undocumented 1,800-second
  long-response TTL never applied, so this removes a false promise rather than changing the
  effective lifetime. An answer such as "Bitcoin is trading at a record high as of today" is no
  longer cached just because the phrase is mid-sentence.
- **Image attachments are understood by the chat provider.** A message may carry up to four
  PNG, JPEG, GIF, or WebP images, with or without text. The current turn is sent to the
  OpenAI-compatible chat provider as an `image_url` data part; history stays text-only, and
  history records `[image: <filename>]` labels rather than image bytes. Perplexity never receives
  image data and an image request is not rerouted to it. The bot always verifies the bytes
  against the declared content type and skips a mismatch. `VISION_ENABLED=false` restores the
  previous behaviour of ignoring attachments. Cache keys include a digest of each image, so the
  same text with a different image cannot reuse an answer.
- **Long code fences are split, not dropped.** A fenced block larger than one Discord
  message is split at a line boundary, closed at the end of the chunk, and reopened with the
  same language tag in the next chunk. Every code line and the prose after the block are
  delivered, and each chunk has balanced fences. A single line wider than the limit is
  hard-wrapped rather than dropped; only the 50-chunk cap still truncates content.
- **The truncation notice reports the original answer length.** It says the bot's delivery
  limit was reached instead of blaming Discord for a cap the bot chose.
- **A partial answer that hit the provider's output-token limit says so.** Both the chat and
  Perplexity adapters report the normalised length signal, and delivery appends one fixed
  notice line after the visible partial answer. The notice is bot text, is not written into
  conversation history, and does not change the system prompt. A partial answer is also not
  cached, so a later identical request asks the provider again instead of replaying the cut-off
  text.
- **An answer survives its question being deleted.** Every answer is sent with
  `channel.send` and a reference built with `fail_if_not_exists=False`, so Discord delivers
  the same content once to the channel with the same mention policy instead of rejecting a
  reply and losing the answer. The bot no longer guesses Discord error codes to detect a
  missing target.
- **Connection notices describe the bot's situation.** The fixed network and Discord notices
  say the bot could not reach its service and ask the user to try again shortly; neither asks
  the user to check their own network or claims a reconnect that does not happen.
- **Embed heads never split a citation marker or a code fence.** A split that would land
  inside `[n]` moves the marker whole into the next embed, and long fences are closed and
  reopened with the same language tag.
- **One parser decides what is code, and every chunk is sanitised after splitting.**
  `tree-sitter-markdown` supplies the spans to both the sanitiser and the splitter. Only a
  closed fence opened and closed by exactly three backticks, with no other triple-backtick
  run outside it, is protected; a closed inline code span is protected only when neither
  its opener nor its closer is backslash-escaped and the text does not mix backtick run
  lengths. Tilde fences,
  four-or-more-backtick fences, indented blocks, unclosed fences, and every uncertain shape
  protect nothing. Outside those regions parser-reported links, images, and autolinks become
  their label text or a neutralised URL, then catch-all passes break every `](`, add a
  zero-width space after every `://`, and separate `<` from a following scheme. Definition
  shaped lines stay as text with an invisible separator instead of being deleted. Chunk
  boundaries use the same protected fences, close and reopen them with the same language
  tag, and each final chunk is sanitised independently; a split-only Discord pairing still
  places a boundary for a block CommonMark does not recognise, and those extra spans never
  suppress sanitisation. Routing keeps its own masker because cues inside dangling pasted
  code must not decide a route.
- **No line is deleted to neutralise a link.** A line shaped `[label]: destination` is
  ordinary text to Discord; its URL receives the zero-width space and the definition syntax
  is broken with an invisible separator so a CommonMark renderer cannot resolve it. Several
  URLs in one whitespace-free run are all neutralised, and nesting depth no longer limits
  the rewrite. Mention neutralisation (`@everyone`, `@here`, raw user/role/channel mentions)
  still applies everywhere, including inside code.
- **Bare `www.` addresses in answers are broken like links.** Model text such as
  `www.example.com/login` now receives a zero-width space after `www.` so Discord cannot
  turn it into a clickable link. A `www.` inside a longer word, protected inline code, a
  fenced block, or a trusted citation URL is unchanged. Bare domains without `www.` and
  without a scheme, such as `example.com` or `main.py`, are left readable because Discord
  decides those.

### Added ✨

- **`PERPLEXITY_INPUT_TOKENS` and `PERPLEXITY_CONTEXT_WINDOW`**: control the prompt budget
  and context window for the Perplexity Sonar path only. Defaults are 111,000 and 128,000;
  the 128K figure comes from the former Sonar model page, and the Agent API models page
  publishes no context figure. The chat path keeps `INPUT_TOKENS` and `CONTEXT_WINDOW`.
- **`ROUTER_CLEF_API_KEY`**: optional dedicated credential for the Clef decision endpoint. When it is
  unset, `OLLAMA_API_KEY` from the environment is eligible, and `OPENAI_API_KEY` is eligible only when
  `OPENAI_API_URL` is an Ollama Cloud URL. A key issued for another provider is never sent to Clef.
  Prefer the environment variable because the value is a secret.
- **`ROUTER_CLEF_MODEL`, `ROUTER_CLEF_THRESHOLD`, and `ROUTER_CLEF_TIMEOUT_MS`**: select the
  Clef decision model, the probability at or above which it routes web, and the hard total
  deadline for one decision. They are ignored unless `ROUTER_MODE=clef`.
- **`WEB_TOOLS`**: offer native `web_search` and `web_fetch` tools to Ollama-compatible chat
  providers; defaults to true. OpenAI endpoints never receive these tools.
- **`REASONING_EFFORT`**: sent as `reasoning_effort` with chat requests; defaults to `high`. Valid
  values are model-defined, and reasoning tokens count toward the output cap.
- **Optional Clef decision-model router.** `ROUTER_MODE=clef` asks Ollama Cloud's Clef model
  (`/v1/systemone`) one bounded yes/no question per message (~0.4 s, consuming tokens);
  `heuristic` remains the default. Network, timeout, HTTP, or malformed-response failures fall back
  to the deterministic gate, and a missing key selects it at startup.
- **`VISION_ENABLED`, `VISION_MAX_IMAGES`, `VISION_MAX_BYTES`, and `VISION_TOKEN_ESTIMATE`**:
  control image attachment handling, per-image size and count caps, and the flat prompt-token
  estimate charged per image during budget trimming.
- **`tree-sitter` and `tree-sitter-markdown` are runtime dependencies.** Both are MIT
  licensed and actively released. `tree-sitter` 0.27.0 ships CPython 3.12 wheels for
  manylinux x86_64 and aarch64 and for musllinux x86_64, but not musllinux aarch64;
  `tree-sitter-markdown` 0.5.4 ships wheels for all four. `python:3.12-slim-bookworm` is a
  manylinux image, so it needs no compiler; a musllinux aarch64 image would need one for
  `tree-sitter`. They provide the shared code-region parser used by output sanitisation and
  message splitting.

### Changed 🔁

- **The launcher prefers the project venv.** `.venv/bin/python3` is tried first when its
  core dependencies are importable, then the shell-activated venv, then pyenv, then the
  system interpreter. The docs match the new order.
- **CI smoke-tests every installed `src` module.** The wheel job now imports each module
  under the installed `src` package, so a broken import in the bot, health server,
  providers, or routing fails the build.
- **Cache and conversation TTLs use the monotonic clock by default.** A wall-clock
  step no longer extends or shortens a cached answer or conversation lifetime. Both
  stores still accept an injected clock for tests.
- **Sanitiser link scans are single pass.** The trusted-link pass searched
  for a closing angle bracket from every unclosed `](<` marker, and the
  bare-URL allowlist searched a lowercased copy for every scheme. The markdown
  pass now caches the next `>` (including "none"), and the scheme search runs
  on the original text, so both scans are linear in the answer length.
- **Link counting uses an indexed lookup.** `count_links()` now compares each
  bare URL with the one link span that could contain it instead of scanning
  every span, so an answer with thousands of links no longer spends quadratic
  time deciding whether to suppress embeds.
- **The fallback router cache is bounded and closed.** When no router is injected, the
  orchestrator keeps at most eight cached fallback routers, closes the oldest when a new
  entry arrives, and closes every remaining one at shutdown, so the Clef HTTP clients do
  not leak.
- **The health endpoint is served by aiohttp.** `HealthServer` and `create_health_app()`
  keep the same `/health`, `/health/live`, and `/health/ready` routes and JSON bodies, but
  the `starlette` and `uvicorn` runtime dependencies are gone; `aiohttp>=3.10,<4` is
  declared instead. A bind or startup failure still disables the endpoint without stopping
  the bot.
- **The conversation and response caches now use `cachetools`.** The hand-rolled history and
  bot-streak TTL maps and the response LRU cache are replaced by `TTLCache` and `TLRUCache`
  with the same injected clock, sliding expiry, LRU eviction, and conversation-scoped keys.
  `cachetools>=8.0.2,<9` is a runtime dependency. The fixed-window rate-limit map stays a
  plain dict-plus-sweep because its window reset is not TTL eviction.
- **Default capacity is right-sized for a 1M-token model.** `INPUT_TOKENS` defaults to 250,000,
  `OUTPUT_TOKENS` and `PERPLEXITY_OUTPUT_TOKENS` to 16,384, and `CONTEXT_WINDOW` to 1,000,000;
  the input-token warning threshold is now 1,000,000, and the output-cap ceiling is 128,000,
  independent of the context window. Conversation history defaults to 100 entries with a
  7,200-second idle TTL.
- **Cache capacity and connection-pool defaults are larger.** The response cache holds 2,000
  entries, chat-provider pools default to 100 connections/20 keepalive, Perplexity pools to
  40/10, and Perplexity requests allow up to four `max_steps`.
- **Local environment references were scrubbed from the documentation.** No hostnames or
  private configuration filenames are published.
- **Provider calls share one narrow adapter protocol and registry.** The Chat Completions
  payload, tool loop, and response parsing live in a chat adapter; the Agent API payload,
  Responses call, and citation extraction live in a Perplexity adapter. A registry supplies
  the provider names used by health checks, the health server, and the breaker table, so those
  lists no longer drift independently. The public `process_openai_message()` and
  `process_perplexity_message()` signatures are unchanged.
- **Configuration examples and docs use the new defaults.** `config.ini.example`, `.env.example`,
  the README, setup, configuration, security, architecture, connection-pooling, validation, and
  provider-contract docs describe the OpenAI-compatible provider with Ollama Cloud as the default.
- **`scripts/probe_providers.py` probes the configured `OPENAI_API_URL`** instead of a hardcoded
  endpoint.
- **Router documentation rewritten to match the gate**: `docs/routing/DESIGN.md` now describes what
  ships; the sealed corpora are a behaviour-pinning fixture, not a scoreboard; the previously
  assert-free `test_corpus.py` fails on drift; overrides are evaluated on code-masked text, so an
  instruction inside a fenced block no longer routes web.
- **Mention policy has one owner.** Only `message_splitter._deliver()` constructs
  `discord.AllowedMentions`; operational notices pass their permitted user to
  `safe_discord_send()`, which delegates to the same helper. The source guard now detects
  qualified, unqualified, and aliased construction calls, and an end-to-end test checks that
  model-output mentions are neutralised in the text actually sent.
- **CI tests the declared minimum dependency versions.** A `min-versions` job installs
  runtime requirements with `--resolution lowest-direct` and the test tools at their
  declared floors, then runs the suite. The ordinary test job still follows the latest
  allowed releases, so a floor-only failure now fails the build instead of reaching an
  operator.

### Fixed 🔧

- **An invalid log-colour value no longer forces colour on.** `DISCORDIANAI_LOG_COLOR=maybe`
  used to count as an explicit choice and turn colour on, and the copied example set
  `false`, which turned colour off even on a terminal. Only a recognised boolean now
  counts as explicit; unset, blank, or invalid values fall back to terminal detection,
  and `config.ini.example` leaves the key commented out. `tests/test_log_colour.py`
  covers the invalid, true, and false cases.
- **Output-token warnings and fatal bot errors are logged once.** The startup check and
  the full API validation both logged the same output-cap warning, and `bot.run_bot` and
  `main.main` both logged a fatal run error with a traceback. The startup check now leaves
  warnings to the full validation, and the entry point logs the fatal error once.
  `tests/test_validation_honesty.py` and `tests/test_main.py` count one record each.
- **A port or size is no longer mistaken for a year.** A question such as "what port
  does postgres listen on, 5432?" went to web search because any four-digit number
  from last year upward counted as a current-year cue. The year cue now covers last
  year, this year, and next year only, so a port or size no longer decides the route.
  `tests/routing/test_features.py` covers the window and the rejected numbers.
- **A local-only instruction needs whole words.** An override phrase such as
  "no web" matched inside "casino website" and "piano webinar", so the bot
  answered locally with no web access. Every override phrase now has a word
  boundary where it starts or ends with a letter, while "no web please",
  "do not search", and "answer from memory" still match. The same change
  covers the web-instruction phrases, so "research the web app" and "recheck
  online" no longer count as explicit search requests.
  `tests/routing/test_lexicon.py` covers both override groups.
- **A failed stop refuses to start a second instance.** When the old process survived the
  final signal, the launcher still started a new bot, giving two gateway sessions on one
  token. The stop helper now waits briefly after `SIGKILL`, reports the surviving PID as
  an ERROR, and returns failure; the launcher exits non-zero without starting and leaves
  the PID file so the next attempt retries. A process that `kill -0` cannot probe is still
  recognised from its `/proc` entry instead of being treated as gone.
  `tests/test_launcher_script.py` stubs an unsignalable process and checks both the helper
  and the PID-file wrapper.
- **The launcher checks every runtime dependency before stopping the bot.** The pre-start
  check imported only `discord`, `openai`, and `httpx`, while the source also needs
  `aiohttp`, `cachetools`, `structlog`, `tree-sitter`, and `tree-sitter-markdown`. After a
  pull that added a package, the launcher could stop a healthy instance and then fail to
  start the new one. It now runs `src/dependency_check.py` in isolated mode, so the exact
  runtime set is checked before any stop, and a failure prints the missing packages and
  the install hint. `tests/test_launcher_script.py` covers the failing and passing check.
- **String environment overrides are trimmed.** A key pasted or mounted from a file with
  a trailing newline or space is now stored without that whitespace for
  `OPENAI_API_KEY`, `BOT_PRESENCE`, `GPT_MODEL`, and every other string override,
  matching the config-file path. The two API keys and `REASONING_EFFORT` keep their
  explicit-empty meaning. `tests/test_config_robustness.py` covers a key with a newline
  and a presence with a trailing space.
- **A blank list override leaves the config-file list alone.** `ALLOWED_CHANNELS`,
  `ALLOWED_GUILDS`, `ALLOWED_CHANNEL_IDS`, and `ALLOWED_GUILD_IDS` set to an empty or
  whitespace-only environment value used to replace the file's list with `[]`, and an
  empty guild list dropped the guild scope. A blank value now means "not set" for these
  keys as it already did for scalar settings; a non-blank value still overrides.
  `tests/test_config_robustness.py` covers all four keys.
- **A stop before `on_ready` no longer skips graceful shutdown.** The dependency
  container always exposed the `_health_task` key with a `None` value, so a stop
  before the health monitor existed raised `AttributeError`; the guard logged a
  timeout and called a hard exit, leaving provider pools and the Discord
  connection open. Shutdown now skips an unset task, contains a failing pool
  close so the router and gateway still close, and logs a timeout and any other
  failure as separate messages. `tests/test_bot_manager.py` covers both paths.
- **A failed continuation no longer re-sends the whole answer.** When the head embed was
  accepted and a later continuation failed, the delivery error triggered the text fallback
  for the entire answer, duplicating it and repeating the mention prefix. The continuation
  error now propagates; only a failed head embed falls back to split text, and that happens
  before anything has been sent.
- **`--conf=VALUE` is matched by the launcher.** Stop and the straggler scan now read both
  `--conf VALUE` and `--conf=VALUE`, so a bot started in the joined form cannot be missed
  and left running beside a new instance on the same token.
- **A chat answer with no visible content is not stored.** An answer that sanitises to an
  empty string, such as a label-less link, now returns the existing no-response notice
  instead of being written to conversation history and the response cache.
- **Health probes use the configured `WEB_TOOLS` value.** The adapter built for the
  startup probe no longer ignores the setting; it inherits the same policy as the
  production client.
- **A closed Clef router refuses synchronous decisions too.** `decide_sync` now returns
  the deterministic fallback without building another HTTP client after `aclose()`.
- **Readiness waits for `on_ready`.** The manager marks the gateway disconnected before
  login, so `/health/ready` is 503 while discord.py already reports `is_ready()` true but
  the gateway handler has not run.
- **A blank `DISCORDIANAI_LOG_COLOR` no longer forces colour on.** The presence of the
  key used to count as an explicit choice, so a blank `[Logging]` value or environment
  variable overrode terminal detection with the default `true` and coloured redirected
  logs. A blank value is now treated as unset, matching the config-wide blank-value rule;
  `false` still forces colour off.
- **The launcher rejects an unknown option before stopping anything.** The `--config=FILE`,
  `--folder=DIR`, and `--install-systemd=FILE` forms are accepted. Any other option prints
  the bad argument and a usage line, exits 2, and sends no signal. The run path resolves the
  config file before the stop step, so `--config=prod.ini` with a missing file cannot stop a
  healthy `bot.ini` instance.
- **A dollar sign survives systemd unit generation.** `ExecStart` escapes `$` as `$$`, so a
  project path such as `price$home` is not treated as a variable name.
- **`--install-systemd` accepts an absolute config path and restarts an active unit.** The
  install path uses the same config resolver as the run path. Re-installing a running unit
  issues `systemctl --user restart` instead of a no-op `start`.
- **The launcher waits for a straggler to exit.** The PID-file path and the straggler scan
  share one bounded signal/wait/force-kill helper, so a new instance starts only after the
  old process for the same config is gone.
- **Trailing-slash health probes work again.** `GET /health/`, `/health/live/`, and
  `/health/ready/` return the same status and JSON body as the slash-less routes.
- **An idle open breaker stops reporting unhealthy after its timeout.** Once the breaker's
  recovery timeout has elapsed, `/health` reports the provider healthy and returns 200; within
  the timeout it remains 503. The status vocabulary has no non-failing "recovering" value, so
  the recovering state maps to healthy while the breaker state still reads `OPEN`.
- **Liveness answers before Discord login.** The health server starts in `setup_hook`, so
  `/health/live` returns 200 while login and the first gateway connection are in progress.
  `/health/ready` stays 503 until `on_ready` records a connected gateway.
- **A routing lexicon that is not UTF-8 follows the local fallback.** A decode
  error used to escape `Lexicon.load` and abort startup even though a missing or
  corrupt lexicon already produced the documented local-only router. The loader
  now reports it as a lexicon error, so `build_router` keeps the bot answering.
- **A closed Clef router stays closed.** Shutdown closes the pooled HTTP client,
  but the next decision used to build a new client that nothing closed again.
  A closed router now logs once and answers through the deterministic gate
  without reopening a connection.
- **A port number or a row count is not an HTTP status.** The text fallback now
  reads a status only when the message names one (`HTTP 429`, `status 429`, or
  `error code: 429`). A connection refused on `port 443` is retried as a connection
  error where no request was established, and prose such as `processed 429 rows`
  no longer becomes a rate limit.
- **`WEB_TOOLS=false` reaches the chat provider.** The loaded value now travels into
  the bot's dependencies, so the Ollama-compatible path omits `web_search` and
  `web_fetch` as documented; it previously always offered them because the
  dependency kept its own `True` default.
- **A dotted capital I no longer shifts trusted citation links.** The
  bare-URL allowlist searched a lowercased copy and applied those offsets to
  the original text, so `İ`, whose lowercase form is two code points, made an
  exact trusted URL miss the match and lose its link. The search now matches
  case-insensitively on the original text, so offsets stay aligned.
- **A Discord send timeout is not retried, and the send retry is bounded.**
  A send whose outcome is unknown now gets one attempt instead of repeating a
  message that may already have arrived, and the retry sequence honours the
  same 90-second deadline as provider calls. A 429 carrying `Retry-After` is
  still retried within the existing cap.
- **An answer with nothing left after sanitising is treated as no response.**
  Whitespace-only output and output such as `[](https://x)` were sent as empty
  content, which Discord rejects, so the user saw the generic processing error.
  The answer path now sends the fixed no-response notice instead, and the
  Perplexity wrapper drops an answer that sanitises away before it is cached or
  recorded in history.
- **A rejected truncated-answer embed falls back to text.** When an answer that
  hit the provider's output limit was sent as an embed, a Discord rejection of
  that embed left the user with the generic processing error. The truncated
  path now delivers the split text, matching the normal embed path.
- **The dependency gate runs before third-party imports.** A missing package now produces
  the friendly `Missing required packages` message and exit code instead of a raw
  `ImportError`, and the no-`ALLOWED_CHANNELS` warning is logged once instead of twice.
- **An embed description cannot exceed Discord's 4096-character limit.** Sanitising can
  insert zero-width spaces and make a description longer than the text that built it, so
  every description is clamped after sanitising with the existing `...` marker.
- **Deeply nested link labels no longer raise `RecursionError`.** The sanitiser renders
  nested labels only 100 levels deep; beyond that the label is sanitised as ordinary text,
  so an adversarial nesting answer still produces a deliverable string.
- **Delimiter-dense answers cannot stall the inline parser.** Text with more than 2,048
  emphasis, strikethrough, or spoiler marker characters skips the inline grammar. Links are
  still neutralised by the catch-all passes, mentions are still neutralised, and a closed
  fence still passes through.
- **A lone UTF-16 surrogate no longer aborts delivery.** The sanitiser replaces an
  unencodable surrogate with `?` before parsing, and the parser's byte-offset table uses
  the same replacement width, so one bad character cannot fail the whole answer.
- **The generated systemd unit quotes only word-list directives.**
  `--install-systemd` no longer wraps `WorkingDirectory`, `StandardOutput`, or
  `StandardError` in quotes, which systemd treated as part of the path and rejected with
  `path is not absolute`. `ExecStart` words and each `ReadWritePaths` path stay quoted,
  percent signs are doubled, and `Environment=` quotes the whole assignment when its value
  contains spaces. A unit generated for a path with a space now passes
  `systemd-analyze verify`.
- **One masked link no longer suppresses embeds by itself.** `count_links()` counts a
  `[title](url)` once instead of also counting its destination, and it ignores filenames
  such as `main.py` and `utils.py`. A single masked link therefore stays below the
  two-link embed-suppression threshold.
- **Delivery splitting is linear and the fence pairing runs once.** Each chunk used to
  slice off the remaining text and rescan it for code fences, so doubling an answer of
  triple-backtick runs multiplied delivery time by four to six. The split-only Discord
  pairing is now a single forward pass with equal-length runs kept outermost first, which
  preserves the `a-fence-nested-looking` golden boundary. Fence spans are planned once, and
  every later chunk walks an offset into the original text instead of slicing and
  reparsing the remainder, so the whole delivery is linear in the input size.
- **User-caused client errors no longer open the provider breaker.** A deterministic 4xx
  caused by the request itself (400, 409, 413, 422, and other client errors except 401, 403,
  404, 408, and 429) means the provider answered and rejected the request, so it does not
  count as a failure or mark the provider unhealthy; a success while the breaker is closed
  now clears the consecutive-failure count. A 400 with `invalid_model` or `model_not_found`
  is a configuration error and counts.
- **Retries follow the wrapped transport cause.** A connect timeout is retried because no
  request was sent, while read timeouts, read errors, and protocol errors after send are
  not. A host:port number such as `:443` in a connect message is no longer read as an HTTP
  status, and a structured `insufficient_quota` 429 is not retried and keeps its quota
  notice.
- **Unclassified exceptions are not retried.** The retry policy now refuses an exception
  it cannot classify instead of treating the unknown type as transient. Built-in
  `ConnectionError` still classifies as a network error and remains retryable.
- **Reset, broken-pipe, and aborted connections are not retried.** `ConnectionResetError`,
  `BrokenPipeError`, and `ConnectionAbortedError` can arrive after the request was sent, so
  repeating the call is not provably safe; the bot now reports them instead of sending the
  same request twice. A bare `ConnectionError` still classifies as a connect failure and is
  retried.
- **A malformed `Retry-After` falls back to normal backoff.** A value that is `nan`, `inf`,
  negative, empty, not numeric, or so large that it overflows to infinity is ignored
  instead of becoming a sleep; the retry then uses normal backoff. A valid value is still
  capped at 30 seconds. A `Retry-After: nan` header can no longer hang the retry loop.
- **The budget-conflict warning names the key that supplied each value.** A Perplexity
  request that exceeds its window reports the effective prompt and context keys, so a
  lowered shared `INPUT_TOKENS` or `CONTEXT_WINDOW` is named as the shared key rather than
  as the Sonar default it replaced.
- **An idle provider no longer reads unhealthy.** A configured provider that has never been
  called and has no recorded failure is healthy; only an open breaker or a failure after the
  last success degrades it. `last_success_age_seconds` and `last_success_stale` remain
  diagnostic and do not decide `/health`.
- **The web tool loop answers on its last round.** The fourth round is offered no tools,
  at most three calls per round are executed, and total tool output is capped; capped or
  over-budget calls still receive a short tool result so the model can continue.
- **Single-provider outages show the outage notice.** The processing wrappers can report a
  classified failure instead of swallowing it, so an outage in OpenAI-only or
  Perplexity-only mode no longer tells the user to rephrase the question.
- **A failed provider call logs one traceback.** The retry policy logs its final summary
  without repeating the traceback, the orchestrator no longer logs the classified failure a
  second time, and the delivery helper logs its own final failure once. One logical failure
  now produces one traceback instead of two or three.
- **`/health` reports gateway disconnects.** A disconnect is recorded and reported as
  disconnected even while discord.py's `is_ready()` remains set; `/health/ready` returns
  503 during the outage.
- **Clef honours gate overrides as data.** The gate marks a deterministic override on the decision, and
  Clef returns it without a network call instead of relying on a `reasons` prefix.
- **A chat key without an explicit URL is not sent to Clef.** A direct caller that supplies only
  `OPENAI_API_KEY` no longer has that key treated as an Ollama Cloud credential through an implicit
  default URL. The loaded configuration still carries `OPENAI_API_URL`, so normal deployments that
  use the default Ollama Cloud endpoint keep the existing fallback.
- **The fallback router is built once, not once per message.** When no startup router is injected,
  the orchestrator caches the router for the effective routing configuration instead of calling
  `build_router` for every message.
- **Structured logs carry the Discord context they were given.** The formatter now reads the
  stdlib record extras before removing the record, so `user_id`, `channel_id`, `guild_id`, and
  the logger name appear in both console and JSON output. The adapter attaches ids only; a guild
  name is no longer copied into every line.
- **Exception logs render without the optional Rich package.** Console tracebacks use
  structlog's Rich formatter only when Rich is importable and otherwise fall back to the
  plain structlog traceback renderer, so a pip install or the container image no longer
  prints `--- Logging error --- NameError: Console`. Neither formatter prints frame locals.
- **Provider failures no longer put response bodies in the logs.** The retry warning, the
  OpenAI and Perplexity wrapper failure lines, and the API-call failure line now log the
  exception class, HTTP status code when present, and classified error type instead of the
  exception text. A provider body can no longer reach a log record through these paths.

### Operations ⚙️

- **Markdown-only changes run CI.** The workflow no longer ignores `**.md`, so a
  documentation-only commit still runs the documentation-truth and changelog guards
  instead of landing red on a later pull request.
- **Log rotation works on non-root-owned directories, and container logs are bounded.**
  The logrotate fragment now has an `su USER GROUP` directive next to the path
  placeholder, so logrotate no longer refuses when the project directory is
  group-writable by a non-root group. The shipped compose file caps Docker's
  `json-file` log at three 10 MB files instead of letting it grow unbounded.
- **Repository ignores cover the artefacts the project produces.** Rotated
  `bot.log-YYYY-MM-DD.gz` files, `*.ini.bak-<date>` configuration backups, and local
  state directories are excluded from git and the Docker build context, while
  `config.ini.example` and `tox.ini` stay tracked.

### Security 🛡️

- **An inline code span with markup inside no longer hides a link.** A span whose content
  holds an emphasis, strikethrough, or spoiler marker, or a markdown link with an
  `http(s)` destination, is now sanitised as ordinary text. Discord may pair the backticks
  differently from CommonMark, so copying the span verbatim could deliver a clickable
  attacker URL.
- **A trusted citation exempts only its own destination.** Title text between the
  destination and the closing parenthesis, and any second `](` after it, now go through the
  catch-all passes. An allowlisted first link can no longer carry a second attacker URL
  through the exemption.
- **A malformed config file cannot leak its contents into the fatal log.** The startup
  error names the file, the exception class, and any source line numbers without quoting
  the offending line, and the parser exception is no longer chained. A token on a broken
  line therefore stays out of the CRITICAL message and the rendered traceback.
- **Message text and provider response bodies stay out of the log.** The message processor
  logs the Discord message id and its length instead of the first 100 characters of the
  content, the cache logs the prompt length instead of the prompt, and the chat adapter logs
  only the response type and id when a provider reply has no choices. A DM body, a channel
  question, or a full SDK response can no longer reach the log through these paths.
- **Tracebacks no longer print frame locals.** Console and JSON logs render exceptions without
  the local variables of each frame, so a config dictionary holding an API key, a message
  body, or request parameters cannot reach the log through an exception. Console output keeps
  a readable traceback, and JSON records now carry the formatted traceback text instead of a
  bare `exc_info` object list.
- **The Clef key is scoped to its endpoint.** `ROUTER_MODE=clef` no longer sends the chat provider's
  `OPENAI_API_KEY` to Ollama Cloud when `OPENAI_API_URL` points at another host. Existing Ollama Cloud
  deployments keep working with no config change.
- **A link cannot survive a chunk boundary.** The sanitiser runs again on every final
  chunk after splitting, and a split never protects text the region function did not
  protect. A URL inside an inline code span that the split cuts is therefore neutralised in
  the delivered chunk instead of becoming clickable.
- **A fence is protected only where Discord ends it.** Discord pairs triple-backtick runs
  sequentially anywhere in the text, while CommonMark requires a line-start closer. A fence
  with a stray triple-backtick run between its opener and closer is now treated as ordinary
  text, so a link after that run is neutralised instead of being delivered live. Inline code
  spans follow the same sequential pairing, and blank lines or backslash-escaped backticks
  can no longer shift the protected span away from Discord's boundary.
- **A code span with an escaped closer protects nothing.** When a parsed inline span ends
  at a backslash-escaped backtick, Discord does not close the span there, so the parsed end
  is not trustworthy. The span is treated as ordinary text and any link inside it is
  neutralised instead of being delivered live.
- **An angle-bracket link is neutralised whatever its scheme.** A parser-reported autolink
  such as `<steam://run/123>` or `<ftp://host/x>` now receives the same zero-width break
  after `://` as `http` and `https` text. Previously only those two schemes were broken, so
  another scheme could survive as clickable text.

### Tests ✅

- **Link-count work is measured in span comparisons.** The helper test now counts each
  examined link span, so a reintroduced linear scan fails the 3,000-match bound instead of
  passing on one lookup per match.
- **Startup-claim docs check matches whole words.** "exit" inside "perplexity" no longer
  satisfies the abort-wording requirement, and negated claims such as "does not prevent
  startup" are excluded.
- **Delivery complexity is guarded by scaling, not a single timing.** The guard builds
  every adversarial shape, including triple-backtick runs and mixed mid-line fences, at
  32,000 and 64,000 characters, then compares work counters rather than elapsed time. It
  fails when the 64,000-character run uses more than 2.5 times the bytes passed to
  `Parser.parse` (plus 4,096) or more than three times the parse calls (plus two) of the
  32,000-character run. A separate check delivers 128,000- and 256,000-character answers,
  confirms the work cap truncates them, and asserts each arrives in under a second.
- **The code-region contract is checked with markdown-it-py on every case, plus the
  Discord parser on the corpus it can parse (crashes bounded at 5 %).** A fixed-seed corpus
  of one thousand adversarial cases, the reported bypasses, and each delivered chunk are
  rendered with markdown-it-py; the Discord-markdown-ast-parser oracle runs on the cases it
  can parse, and its crash share is capped at 5 %. The complexity guard sanitises and
  delivers each 32,000- and 64,000-character adversarial shape once and compares the
  parser work counters. The mutation checker now kills a removed `](` pass, a removed `://` pass, a
  delivery path that skips the per-chunk sanitiser, and three parser-backed mutations
  (protect-misaligned-inline-span, protect-unclosed-fence, protect-fence-with-inner-run)
  that protect a misaligned inline span, an unclosed fence, or a fence with an inner run.
- **The mutation checker works on a scratch copy.** `scripts/mutation_check.py` copies
  the checkout (minus VCS state, caches, logs, local `*.ini`, and `.env`) into a temporary
  directory before applying mutations, so an interrupted run cannot corrupt the working
  tree. Three stale mutation anchors were re-anchored to the current source, and
  `tests/test_mutation_check.py` fails if any anchor stops matching.
- **The safe embed limit is an absolute number in the split assertion.** The expected head
  and tail now use `3840` instead of importing the constant under test, so a change to the
  production safe limit fails this delivery contract instead of silently moving with it.
- **The Discord send failure test patches its retry sleep.** The failure case waited a
  real second before retrying; it now patches `src.error_handling.asyncio.sleep` and
  asserts the one backoff, so the suite has no wall-clock wait on this path.
- **The launcher stop test waits for the child before asserting.** The test used to
  check `kill -0` immediately after the stop helper returned, which raced the child's
  exit and intermittently exited 5. Waiting on the child first makes the test report a
  real stop failure instead of a scheduling artifact; 50 consecutive runs passed.
- **A web route calls Perplexity at most once.** When the initial web call fails and the
  chat fallback also returns nothing, the test asserts the request tail returns the
  both-services notice without calling Perplexity a second time. Removing the attempt
  ledger now fails the suite.
- **Clef host eligibility is pinned against lookalike names.** A suffix such as
  `ollama.com.evil.example`, userinfo such as `ollama.com@evil.example`, a path containing
  `ollama.com`, and a prefix such as `notollama.com` are all refused. The test fails if the
  exact-hostname check is weakened to a substring match.
- **Root logging is restored between tests.** A test that configures production logging
  no longer leaves its rich handler installed for later tests, which had made traceback
  rendering, not retry sleep, the slow part of the outage tests.
- **Single-provider outage tests prove their retry sleep is intercepted.** The retry
  sleep is patched at its real boundary in `src.error_handling`, and each test asserts
  that one backoff sleep happened, so the suite exercises the retry path without a real
  backoff wait.
- **Default-provider regression coverage** pins the Ollama Cloud URL and model, permissive model
  validation, `REASONING_EFFORT` overriding, and the `max_tokens` request payload.
- **Provider contract coverage** runs both adapters against stubbed SDK clients: request shape,
  text and citation extraction, the tool-loop round trip and cap, error classification, breaker
  opening, probe success and failure, and cache parity between the two providers.
- **Vision coverage** checks magic-byte sniffing for PNG, JPEG, GIF, and WebP; pre- and
  post-download size caps; the image-count cap; skipped and unreadable attachments; base64
  round-tripping; multimodal message shape; image-aware token accounting and truncation; cache
  keys scoped by image digest; image-only messages; disabled-vision short-circuiting; local route
  forcing; Perplexity refusal; and history labels without base64.
- **The sanitiser is checked against an independent CommonMark parser.** A fixed-seed
  corpus of backticks, fences, escapes, autolinks, reference links, and inline-code labels
  is rendered with `markdown-it-py`; any `<a>` element or surviving mention fails the test,
  and the same corpus runs through the embed description path.
- **Provider environment variables cannot leak into a test.** An autouse fixture removes
  `OLLAMA_*`, `OPENAI_*`, `PERPLEXITY_*`, `ROUTER_*`, and `DISCORD_TOKEN` before each test,
  so the suite is identical under `env -i` and the normal shell.
- **A retired model is not a neutral 400.** A real SDK `BadRequestError` built from the
  provider's `invalid_model` response and the OpenAI-style `model_not_found` body opens the
  provider breaker and makes `/health` report the provider degraded.
- **A tiny prompt budget is rejected.** `INPUT_TOKENS` and `PERPLEXITY_INPUT_TOKENS` below
  1,000 are startup errors, while 1,000 is accepted.
- **The launcher reads its stop timeout and PID assignment from code.** The
  `DISCORDIANAI_STOP_TIMEOUT` override is exercised, the script's own `PID_FILE=` line is
  evaluated for two configs that share a basename, and a config path with a space is matched
  by the straggler scan.
- **A truncated chunk closes its open fence.** A one-chunk cut inside a fenced code block
  ends with the closing marker before the length notice.
- **Delivery splitting coverage.** A long fence spanning three or more messages delivers
  every line with balanced fences, and the test also checks prose after the fence, the
  first-chunk mention limit, the chunk-cap notice's original length, citation-marker and
  fence safety in embed heads, and code-preserving sanitisation while mentions stay
  neutralised.
- **The floor-version suite can run its own tests.** The health tests read the bound port
  through the runner's address list instead of a newer `TCPSite` attribute, and the recorded
  Perplexity 400 test builds its HTTP stub with whichever HTTPX class the installed openai
  SDK accepts. The formatter test already runs without the optional Rich package. The full
  suite now passes against every declared minimum runtime version.

### Documentation 📝

- **Provider validation prose states the startup rule that ships.** `docs/Security.md`
  now explains that a provider selected by a key, base URL, or model without a key stops
  startup, even when the other provider has a key.
- **Delivery and security docs state the code-protection rule that ships.** The shared
  region function, the two neutralisation layers, per-chunk sanitising, the no-deletion
  rule, and the new runtime dependencies are recorded in `docs/MessageSplitting.md`,
  `docs/Security.md`, `docs/Architecture.md`, and the dependency notes in the README and
  setup guide.
- **The scripts README matches the shipped tools.** The unimportable
  `debug_perplexity_citations.py` helper is deleted; `scripts/README.md` now documents
  only the scripts that exist, what each reads, and which ones write files by design.
- **Routing docs describe the masking, credential, lifecycle, and reroute rules.** `docs/routing/DESIGN.md`,
  `docs/HybridMode.md`, and `docs/Configuration.md` now state that bearing and override cues are
  code-masked while code-shape and traceback framing cues still read the original text, how the Clef
  key is resolved, that the router is built once and closed at shutdown, and that only first-person
  browsing admissions trigger the safety-net reroute.
- **`docs/Vision.md`** documents how to send images, the provider used, limits, fallback
  behavior, and the privacy note that images leave the bot for the configured chat provider.
  The README documentation map and `docs/Configuration.md` link to it.

### Notes ⚠️

- **Existing virtual environments must reinstall the runtime requirements.**
  `tree-sitter` and `tree-sitter-markdown` are now runtime dependencies. The startup
  dependency check stops with a clear `Missing required packages` message naming them;
  run `pip install -r requirements.txt` (or `pip install -e ".[dev]"`) in the existing
  environment before upgrading.
- **Non-Latin and emoji history trims earlier.** Prompt estimates now charge U+0080-U+07FF
  at one-half token per character, U+0800-U+FFFF at 0.8, and astral-plane characters such
  as most emoji at 1.7, before the existing 1.1 margin. A history that was previously
  under-counted at the ASCII rate is trimmed sooner; ASCII prose and code keep the
  one-quarter token per character estimate.
- **Local scraping is gone, and three scrape-budget keys are removed.**
  `MAX_URLS_PER_MESSAGE`, `MAX_TOTAL_SCRAPED_CHARS`, and `SCRAPE_DEADLINE_SECONDS` are no
  longer read because URL fetching now happens in the provider tools. An existing
  `config.ini` that still sets them loads and ignores them; delete those lines during the
  upgrade. `PERPLEXITY_INPUT_TOKENS` and `PERPLEXITY_CONTEXT_WINDOW` bound the bot's own
  prompt on the web path; they do not replace a scraping budget because fetching now happens
  in the provider tools.
- **Double percent signs are no longer collapsed.** A value that wrote `%%` to mean one
  literal `%` now keeps both characters; write a single `%`.
- **Clef no longer reuses the chat key for a local daemon URL.** With an `OPENAI_API_URL`
  such as `http://localhost:11434/v1/`, `OPENAI_API_KEY` is not eligible for Clef. Set
  `ROUTER_CLEF_API_KEY` or `OLLAMA_API_KEY` to use `ROUTER_MODE=clef`.
- **A missing `--conf` file now stops startup.** The 0.4.0 configuration loader allowed an
  explicitly requested file to fall through to environment defaults. Every entry point now
  rejects a missing file; the launcher is not the only path that must fail.
- **The launcher PID file is per config.** An existing `.bot.pid` is honoured only when its
  process runs the same config, then removed; new runs write
  `.bot-<stem>-<hash>.pid`.
- **A configuration that was legal on 0.4.0 can now fail to start.** `INPUT_TOKENS` plus
  `OUTPUT_TOKENS` must fit `CONTEXT_WINDOW`, and `PERPLEXITY_INPUT_TOKENS` plus
  `PERPLEXITY_OUTPUT_TOKENS` must fit `PERPLEXITY_CONTEXT_WINDOW`. A config that exceeds
  either window aborts at startup with an ERROR naming the keys; lower the budget or raise
  the window before upgrading.
- **Retries are narrower than before.** `ConnectionResetError`, `BrokenPipeError`, and
  `ConnectionAbortedError` are no longer retried, an exception the policy cannot classify
  is refused instead of treated as transient, and a `Retry-After` header of `nan` or `inf`
  no longer turns into a sleep. Retries still cover requests that provably never left the
  bot, 429 responses with a usable `Retry-After`, and 5xx responses.

## [0.4.0] - 2026-10-28

### Behaviour changes

- **Routing is now an evidence model, and the old regex chain is gone.** Each message gets one decision
  from `src/routing/`: bearing evidence (a status, price, version, event, or other mutable value) may
  route to Perplexity, while framing (question shape, opinion, creative, social, proper names) can never
  decide alone. The ordered regex chain and its pattern lists were deleted rather than left dormant, so
  there is no flag to restore the old behaviour. Measured on the corpora committed under
  `tests/routing/corpora/`: recall **0.728**, precision **0.716**, accuracy 0.779 over 289 scored rows,
  against the deleted chain's 0.526 / 0.682 / 0.716 on the same rows. On ordinary traffic the router is
  0.722 / 0.897; on a set deliberately built from surface-wording traps it is 0.738 / **0.534**, still
  ahead of the incumbent's 0.405 / 0.486. Precision on trap-heavy input is the known cost of preferring a
  wasted search to a confidently stale answer, and it is stated rather than averaged away.
- **Cache entries carry the routing decision.** Keys now include the service, router id, policy version,
  decision source, function, route salt, and degraded flag, so a web-routed message cannot receive a
  cached local answer and an unsure decision is not stored at all.
- **A degraded fallback stays degraded.** When a web attempt fails and the local answer is returned, the
  entry is marked `degraded=true` and cannot be replayed as a successful web answer.
- **Each provider is attempted at most once per request.** If Perplexity already failed, an OpenAI
  web-inability response returns the local answer with a warning instead of calling Perplexity again.
- **Missing history no longer discards the answer.** A missing conversation manager or a history lookup
  that raises now routes with empty context and still delivers a successful model response.
- **The default model is now `gpt-6-luna`; GPT-5 series models are retired by the provider on 2026-12-11 and remain selectable until then.**
- **Perplexity now uses the Agent API.** Requests go to `/v1/agent` (the SDK uses the `/v1/responses` alias) with `instructions`, `input`, `max_output_tokens`, and the `web_search` tool; answers come from `output` items and citations from `search_results`. `PERPLEXITY_MODEL` defaults to `perplexity/sonar`. Sonar Chat Completions is still supported by the provider but is no longer what this bot uses. **Upgrading: a config that sets `PERPLEXITY_MODEL` to a legacy Sonar id — `sonar`, `sonar-pro`, `sonar-reasoning-pro`, `sonar-deep-research` — must change it to `perplexity/sonar`. The Agent API does not accept the old ids; startup warns and requests fail until the value is updated.**
- **Conversation memory is per channel, not per user.** A DM can no longer be replayed into a public reply, and two channels no longer share context. History already held in memory under the old per-user keys is not reused.
- **Web-search follow-ups keep their thread.** The Perplexity path now receives the conversation history it always claimed to have, so a follow-up is answered with the earlier turns in view.
- **Answers are no longer shared between users through a response cache.** Cache and request-deduplication keys are scoped to the conversation key plus a digest of the conversation, with the requester as a fallback when no conversation key is given, so the same words from two people no longer return one person's answer.
- **Long conversations are trimmed, not failed.** A conversation that outgrows the configured `INPUT_TOKENS` budget has its oldest history dropped; a single oversized message is truncated with a visible `[truncated to fit the token budget]` marker.
- **Threads follow their parent channel.** The bot answers in a thread when the parent channel is allowed.
- **Channel-name allowlists apply in every guild.** `ALLOWED_CHANNELS` names now resolve in every guild the bot is in. `ALLOWED_GUILDS` or `ALLOWED_GUILD_IDS` narrow the search, and `ALLOWED_CHANNEL_IDS` takes precedence when both forms are set.
- **Bot authors are answered without a mention loop.** A bot that addresses the bot is answered like any other sender, but the reply never mentions that bot and never authorises it in `allowed_mentions`. After two consecutive bot-authored turns in one conversation, further bot turns are dropped until a human message resets the streak.
- **Retries are limited to failures a retry can fix.** Connection failures, rate limits and server errors are retried. Read timeouts and deterministic client errors are not.
- **A provider outage fails fast.** Repeated failures open the provider's circuit breaker, so later messages fail over immediately instead of paying another full timeout.
- **`/health` reports observed provider state.** A provider that has never been called is healthy, so silence no longer causes `/health` to report 503. Provider entries include the circuit-breaker state and last success/failure times; a health port that is already in use disables the endpoint without stopping the bot.
- **Error messages separate request failures from configuration faults.** A too-long prompt, a content-filter rejection and a permissions failure are reported as request or authentication errors rather than as a configuration problem.
- **`LOG_FILE` is deprecated and ignored.** It is still parsed for compatibility and logs one startup note, but the bot writes no log file; the supervisor or shell redirect owns log output.
- **Log color follows the terminal unless configured.** When `DISCORDIANAI_LOG_COLOR` is absent, ANSI color is emitted only when the output stream is a terminal. An explicit setting forces colour on or off; the sample `config.ini.example` sets it to `false`, so redirected logs stay plain unless an operator opts in.
- **The package installs as a package.** The wheel contains `src/` instead of scattering top-level modules, and the `discordianai` command works.
- **Some configuration errors now stop startup.** A malformed `OPENAI_API_URL` or `PERPLEXITY_API_URL`, or an output-token cap above 128,000, is fatal. An operator upgrading with one of those settings must fix it before the bot can boot.
- **Citations and mention handling are hardened.** Citations survive to the wire, non-allowlisted links are reduced to their label, bare URLs and autolinks are broken with a zero-width space after the scheme, and a reply's allowed mentions can no longer ping `@everyone` or a role.

### Added ✨

- **Perplexity attribution**: the Perplexity client sends an `X-Pplx-Integration: discordian-ai` header when its base URL host is `api.perplexity.ai`; custom hosts are unchanged.

### Operations ⚙️

- **Log rotation**: `contrib/logrotate/discordianai` is a ready-to-edit `copytruncate` fragment for supervisor-owned `bot.log`; `docs/Daemon.md` explains installation and the copy window.
- **`PERPLEXITY_OUTPUT_TOKENS`**: sets Perplexity's `max_output_tokens` independently of OpenAI's `OUTPUT_TOKENS`; when unset it follows `OUTPUT_TOKENS`.
- **`CONVERSATION_TTL_SECONDS`**: idle seconds before a conversation and its lock are evicted (default 1800).
- **Scrape budgets**: `MAX_URLS_PER_MESSAGE` (default 3), `MAX_TOTAL_SCRAPED_CHARS` (default 60000) and `SCRAPE_DEADLINE_SECONDS` (default 20) bound the work one message can cause.
- **SSRF caveat for HTTPS**: `docs/Security.md` now documents that plain HTTP is pinned to a vetted address while HTTPS relies on a pre-request DNS check, leaving a small DNS-rebinding window in exchange for correct TLS verification.

### Fixed 🔧

- **Cross-routing cache hits**: a web answer and a local answer can no longer share a cache entry, and a
  degraded local fallback is never served as a web answer.
- **Double Perplexity attempts**: the web-inability reroute consults an attempt ledger, so one request no
  longer calls the same failed provider twice.
- **Long answers are delivered completely**: message splitting is iterative and bounded by a 50-chunk runaway cap, so an answer within the provider's output budget is no longer cut off by a recursion-depth guard.
- **Conversation transcript integrity**: answers stay attached to the question that produced them, and a zero consistency lookback now disables lookback instead of reading the whole transcript.
- **Shutdown**: `SIGTERM` and `SIGINT` now stop the bot once, with a bounded wait, instead of crashing or being killed after the launcher's grace period.
- **Rate limiting**: windows are measured with a monotonic clock, so system clock steps no longer refuse valid users or let bursts through.
- **Provider plumbing**: OpenAI and Perplexity share one request-building and error-classification path while keeping separate output caps; startup checks the packages the code imports.
- **Citations and delivery**: one citation formatter and one reply path replace the per-provider duplicates, with consistent splitting for long responses.
- **Documentation truth**: README and docs now match the code for logging, routing, retries, health, provider contracts and deprecated settings, with tests that fail on drift.

### Security 🛡️

- **Scraped pages are data**: page text is wrapped in an explicit untrusted block and delimiters are escaped. Model output is neutralised so scraped pages cannot inject mentions or markdown links, bare URLs, or autolinks into Discord: non-allowlisted links are reduced to their label or broken with a zero-width space after the scheme. A URL that appears inside an allowlisted citation is left intact.

### Tests ✅

- **Coverage**: new regression tests cover channel-scoped conversations, Perplexity history, token budgets, retry policy, SSRF and redirect checks, routing rules, health truth, validation honesty, documentation drift and the changelog/version contract.

## [0.2.9.9] - 2026-06-06

### Fixed 🔧 — Reliability & Concurrency
- **Thread safety**: hardened shared conversation and routing paths so concurrent users no longer trample per-user state under load.
- **Recursion guard**: message splitting now fails safely instead of recursing indefinitely on pathological long responses.
- **Logging crashes**: fixed structured logging setup so `structlog` processor chains no longer break on stdlib logger edge cases.
- **Retry behavior**: standardized transient failure handling around the new flat jittered retry policy.

### Fixed 🔧 — Dead Code & Cleanup
- **Dead code removal**: removed roughly 1.4k lines of stale helpers, legacy branches, and duplicate test scaffolding across bot, processing, and docs-adjacent code.
- **Old API assumptions**: pruned leftover request-library wording and outdated examples that no longer matched the async `httpx` implementation.

### Fixed 🔧 — Async HTTP Migration
- **`httpx` migration**: async HTTP paths now consistently use `httpx` instead of `requests`-era language and examples.
- **Web scraper behavior**: async mock coverage and timeout handling were aligned with the actual async context-manager flow.

### Fixed 🔧 — Final Review Polish
- **Copilot review cycle**: addressed 9 rounds of Copilot review feedback (27 comments total), covering rate limiter refinement, type annotations, docstring corrections, TOML literal string fixes, `noqa` placement, recursion guard budget, stale docs references, test hygiene, and sentinel typing.
- **R9 cleanup**: fixed cooldown transition log ordering so the transition is reachable, and introduced a typed `_StopRetry` sentinel for accurate `web_scraper.py` return annotations.

### Fixed 🔧 — Configuration Gaps
- **Channel targeting**: added and documented `ALLOWED_CHANNEL_IDS` alongside name-based channel allowlists.
- **Health config**: documented the missing `[Health]` section and its runtime keys.
- **Dependency checker**: filled remaining config/validation gaps so startup parsing matches the supported settings surface.

### Fixed 🔧 — Structured Logging
- **`ExtraAdder`**: kept `structlog.stdlib.ExtraAdder` in the processor chain and added test coverage for it.
- **Debug logging**: improved developer-facing diagnostics without changing production log shape.
- **`pad_event_to`**: kept console rendering aligned for fixed-width output.

### Changed 🔁 — Documentation
- **Architecture diagram**: rewrote `docs/Architecture.md` with a clean Unicode box diagram and correct file layering.
- **Message splitting docs**: updated examples to match the current splitter API.
- **Embed limits docs**: refreshed examples to show the real truncation behavior.
- **Perplexity docs**: corrected retry wording to flat jittered retry.
- **Hybrid mode docs**: fixed the Mermaid node collision.
- **Security docs**: added SSRF protection notes for the web scraper.
- **README**: documented `ALLOWED_CHANNEL_IDS` for precise channel targeting.

### Fixed 🔧 — Documentation
- **Stale autodoc reference**: removed `docs/api/api_utils.rst` and its toctree entry after `src/api_utils.py` was deleted — CI Docs Build was failing with `ModuleNotFoundError`.

### Tests ✅
- **Structured logging coverage**: added an assertion that `ExtraAdder` remains in the processor chain.
- **Web scraper coverage**: verified async mock patterns against the current `httpx` flow.
- **Docs integrity guard**: added `test_docs_api_automodule_targets_are_importable` that scans every `.. automodule::` in `docs/api/*.rst` and verifies the target module is importable — catches stale `.rst` files after source deletions before they hit CI.

### Stats 📊
- **Implementation scope**: critical bug fixes, config cleanup, async HTTP modernization, docs refresh, and test hardening.
- **Release quality**: all changes are aligned to current code paths and no stale descriptions remain.

### Fixed 🔧 — Dependency & Configuration (internal QA)
- **`websockets` dependency**: Added `websockets>=16.0` to `requirements.txt` to match `pyproject.toml` declaration and ensure Docker builds include the runtime dependency.
- **`ConnectionPool` config parsing**: Wired `[ConnectionPool]` section parser (`_parse_connection_pool_config()`) into `load_config()` — this section was documented in `config.ini.example` and had defaults defined, but was silently ignored at runtime.
- **`ENTITY_DETECTION_MIN_WORDS`**: Now reads from config file and environment variables (was documented but unimplemented in the parser).
- **`ALLOWED_CHANNEL_IDS`**: Added ID-based channel matching alongside name-based `ALLOWED_CHANNELS` — channel IDs are unique across servers unlike names.
- **`.env.example`**: Created template file with all 21 supported environment variables, commented out with descriptions.
- **`CONTRIBUTING.md`**: Updated Python version from 3.10 to 3.12+ to match `pyproject.toml` requirement.
- **structlog 25.x compatibility**: Removed redundant `structlog.stdlib.add_logger_name` processor that crashes with `None` logger in the `ProcessorFormatter` chain; custom `_add_logger_name` already handles this correctly.
- **CI validation hardening**: added pip install steps for black and ruff in pre-push validation to eliminate version drift between local tools and CI (black 26.1.0→26.5.1, ruff 0.15.10→0.15.16). Resolved 7 formatting/lint violations caught by CI but missed locally.

### Fixed 🔧 — Logging
- **`DISCORDIANAI_LOG_COLOR` default**: Colors are now enabled by default even for non-TTY/file output; only explicit `0`/`false`/`no` disables color.
- **ANSI escape codes in file output**: `ConsoleRenderer` now only disables ANSI when `DISCORDIANAI_LOG_COLOR` is explicitly turned off; colors remain enabled by default even for file output.
- **Duplicate log lines**: Removed `discord.py`'s `log_handler=None` duplication path and the redundant `FileHandler` so messages are emitted once.
- **Clean shutdown logging**: `SIGTERM`/`KeyboardInterrupt` shutdowns no longer dump rich tracebacks with source excerpts and local variables into `bot.log`.
- **Double-format crash**: Removed `structlog.stdlib.add_logger_name` to avoid crashing when the logger is `None`; the custom logger-name processor already handles this case.

### Fixed 🔧 — Source Code Reliability & Security
- **`BotDependencies.__setitem__`**: Added `__setitem__` method to support dict-style writes (`deps["_health_task"] = ...`) — previously caused `TypeError` crash in `on_ready`, preventing health monitoring from starting.
- **`sanitize_for_discord()`**: Wired into all send paths in message splitter — function was dead code, leaving `@everyone`/`@here` unsanitized in AI responses.
- **`run_bot` NameError**: Initialized `deps = None` before try block — if `initialize_bot_and_dependencies()` raised before assignment, the except handler crashed with a secondary `NameError` masking the real error.
- **`asyncio.sleep` in web scraper**: Replaced blocking `time.sleep()` with `await asyncio.sleep()` — 1-3 second sleep was freezing the entire event loop.
- **`time.monotonic()` in CircuitBreaker**: Replaced `time.time()` with `time.monotonic()` for clock-jump safety; added time-based failure count decay to prevent permanent trip from sparse intermittent failures.
- **`FAIL_OPEN_LIMIT` constant**: Added module-level constant replacing magic number `3` for rate limiter fail-open threshold.
- **Perplexity citation extraction**: Fixed `_map_from_metadata()` to store citation URLs instead of raw objects — downstream comparison against string URLs was always failing.
- **Embed truncation logging**: Fixed log message reporting post-truncation length as the "from" value — now reports original pre-truncation length.
- **Message overflow guard**: Added length check after prefix concatenation to prevent exceeding Discord's 2000-char limit when prefix nearly fills the message.
- **OpenAI→Perplexity reroute deduplication**: Moved conversation persistence into the orchestrator after successful responses, keeping `process_*_message()` side-effect free and preventing duplicate history entries during reroutes.
- **Rate limiter fail-open**: Narrowed `except Exception` to catch only transient errors; added fail-open cooldown on repeated failures to prevent permanent rate-limit bypass.
- **Content-Length handling**: Unparseable `content-length` headers in web scraper now proceed with download instead of aborting all retries.
- **uviicorn ImportError**: `HealthServer.start()` now catches `ImportError` when uvicorn is missing and returns cleanly instead of crashing startup.
- **Error classification**: Fixed `"5" in error_msg` matching model names and timestamps; now uses regex word-boundary HTTP status code matching.
- **Decorator kwarg leak**: Changed `kwargs.pop("logger")` to `kwargs.get("logger")` in `handle_api_error` to avoid silently removing legitimate caller kwargs.
- **Double-fault NameError**: Initialized `error_details = None` before `classify_error()` call to prevent `NameError` if classification itself raises.
- **Cache time-indicator blocking**: Changed from substring matching to regex word-boundary matching — responses containing "today" or "latest" in body text are cached unless the word appears in a time-sensitive position.

### Changed 🔁
- **Retry documentation**: Updated `docs/Security.md`, `docs/Architecture.md` with current flat jittered retry defaults (was still showing deprecated exponential backoff values).
- **Timeout documentation**: Updated read timeout documentation to reflect actual values: 45s (OpenAI) / 60s (Perplexity).
- **Docker security**: Updated `docs/Security.md` Docker user from `botuser` to `appuser` to match actual Dockerfile.
- **Entity detection docs**: Fixed `docs/Development.md` claim of "no unnecessary word count thresholds" — now accurately describes `ENTITY_DETECTION_MIN_WORDS=10`.
- **Docs**: Updated `docs/Architecture.md` visual alignment (border overflow, box sizing) and accuracy notes for orchestrator persistence flow, response formatting, and the decorator helper note.
- **Dependency changes**: Removed `requests` from the project and completed the async HTTP migration to `httpx`; updated `openai` 2.32.0→2.41.0, `starlette` 0.45.0→1.2.1, and `structlog` 24.4.0→25.5.0 in `pyproject.toml` and `requirements.txt`.
- **Dev dependency**: Added `httpx2` for `starlette.testclient` compatibility.
- **Architecture diagram**: Standardized file extensions in ASCII diagram; updated ConnectionPooling example to use `ConnectionPoolManager` wrapper; noted caching decorator as aspirational.
- **Sphinx API docs**: Added missing `conversation_manager.rst` to `docs/api/`; fixed copyright year to `2025-2026`; added 27th module to count reference.
- **Usage docs**: Updated `docs/Setup.md` to show `discordian.sh -c config.ini` invocation; `docs/HybridMode.md` to mention `ENTITY_DETECTION_MIN_WORDS`; `docs/Docker.md` to reference launcher and `docker-compose.yml`.
- **Python version docs**: Updated `docs/Python_Versions.md` with pyenv/launcher notes for cron and systemd deployments.

### Tests ✅
- **`logging_adapter.py` coverage**: New `test_logging_adapter.py` with 3 tests covering `ContextualLoggerAdapter.process()` with/without guild context and `get_logger_with_context()` factory.
- **`models.py` coverage**: New `test_models.py` with 5 tests verifying frozen dataclass immutability and correct defaults for all 5 model classes.
- **`py313` tox support**: Added `py313` to tox envlist alongside `py312`.
- **Structured logging race fix**: Replaced `_reset_logging` fixture's global root logger mutation with clean return — eliminating race condition with `pytest-xdist -n auto`.
- **Real sleep removal**: Replaced `time.sleep()` calls in `test_rate_limits_comprehensive.py`, `test_caching.py`, and `test_errors.py` with `unittest.mock.patch` — eliminated ~4 seconds of wall-clock waiting.
- **Benchmark cleanup**: Removed hard timing assertions from `test_performance_integration.py` and `test_load_stress.py` — converted to pure functional assertions.

### Lint ✅
- All 16 ruff warnings resolved across source and tests — zero errors on `ruff check src/ tests/`.
- Import ordering standardized, line length compliance, private member access replaced with properties, magic values extracted to named constants.

### Stats 📊
- **Files changed**: 72 files changed, +2041/-2581 lines
- **Test result**: 584 passed, 0 skipped
- **Lint**: `ruff check src/ tests/` clean
- **Coverage**: maintained at or above existing thresholds

## [0.2.9.8] - 2026-05-04

### Added ✨
- **HTTP Health Endpoint (#210)**: Starlette-based `/health`, `/health/live`, `/health/ready` probes for Kubernetes/Docker health checks. New `HealthServer` class manages lifecycle alongside the Discord bot.
- **Sphinx API Documentation (#205)**: Auto-generated API reference using Sphinx + Furo theme for all 26 source modules. Build with `make -C docs html`.
- **API Call Context Managers (#208)**: `api_context.py` module with `api_call()` async context manager and `call_with_retry()` helper. Unifies timing, error classification, tracking, and logging across all external API calls.
- **Connection Pool Tracking (#212)**: `ConnectionPoolManager` now tracks created HTTP clients with creation timestamps, exposes `get_pool_metrics()` for monitoring visibility, and properly closes all clients on `close_all()`.
- **Structured Logging (#209)**: `structlog` integration with hybrid console/JSON renderer via `configure_structlog()`. All existing `logging.getLogger()` calls are enriched transparently; new code can use `get_structured_logger()` for bound context.
- **Formal Dependency Injection (#206)**: `BotDependencies` dataclass replaces the untyped `deps` dict. Supports `__getitem__`, `__contains__`, `.get()`, and `.to_dict()` for full backward compatibility.
- New runtime dependencies: `starlette>=0.45.0`, `uvicorn>=0.34.0`, `structlog>=24.4.0`.
- New dev dependency: `sphinx>=8.0.0` and `furo>=2024.8.0` under `[docs]` extras.

### Fixed 🔧
- **discordian.sh launcher rewrite**: Fixed `ModuleNotFoundError: No module named 'src'` when running from cron — the script now always `cd`s into the project directory before launching Python.
- **Python resolution**: Removed hardcoded linuxbrew PATH. The launcher now resolves Python in a portable priority order: pyenv → project venv → shell venv → system `python3`.
- **Venv bootstrapping**: Automatically creates a project-local `.venv/` with dependencies if one doesn't exist, using the resolved Python interpreter.
- **Process management**: Replaced bare `pkill` with PID-file based shutdown (SIGTERM → 10s wait → SIGKILL) and stray process cleanup.
- **Startup health check**: Daemon mode now waits 3 seconds after launch and confirms the process survived before reporting success.
- **Version gating**: Added Python ≥3.12 check with a clear error message on older interpreters.

### Added ✨
- **`--install-systemd` flag** on `discordian.sh`: generates and installs a systemd user service from a config file name (e.g., `./discordian.sh --install-systemd bot.ini` creates `discordian-bot@bot.service`). Auto-detects paths, builds PATH dynamically from pyenv and Homebrew (via `brew --prefix`), and enables the service.
- **systemd template unit** (`contrib/systemd/discordian-bot@.service`): reference template for manual setup. Instance name maps to config file (`discordian-bot@bot` → `bot.ini`).
- **docs/Daemon.md**: rewritten with both cron and systemd deployment paths, `--install-systemd` quick-setup, Python resolution order (pyenv first), venv bootstrapping guide, and troubleshooting section.
- **README.md**: added "Running with the launcher script" section with usage examples including `--install-systemd`.
- **`.bot.pid` gitignore**: added PID file to `.gitignore`.

---

### Fixed 🔧
- Classify OpenAI `insufficient_quota` (429) as non-retryable auth error for instant Perplexity fallback instead of wasteful retry loops.
- Added `API_TIMEOUT` to non-retryable error list so read timeouts bail immediately to the fallback service rather than compounding retry delays.
- Symmetrized retry policy across OpenAI and Perplexity: both services now use identical `retry_with_backoff` config (`max_attempts=2`, 2-4s jittered wait, flat delay).
- Disabled OpenAI SDK-level `max_retries` on both clients to prevent nested retry multiplication (SDK + application wrapper compounding up to 6 calls).
- Added application-level `retry_with_backoff` wrapper to Perplexity for transient network/5xx resilience (was previously unprotected outside of SDK retries).
- Increased `httpx.Timeout.read` from 30s to 45s (OpenAI) and 60s (Perplexity) to accommodate high-reasoning and search+citation pipelines.

### Changed 🔁
- Unified retry wait to 2.0-4.0s flat jittered delay (was 1.0s base with exponential growth up to 30s max_delay).
- **CI hardening**: Added Sphinx docs build job to CI (warnings as errors via `-W`), pinned lint deps (`black>=26.1.0`, `ruff>=0.15.4`), removed `docs/**` from path-ignore so doc changes trigger CI, added `testenv:docs` to tox.
- Disabled `autosummary_generate` in Sphinx conf (we use per-module `.rst` files; autosummary was producing 21 duplicate stub warnings for `BotDependencies` fields).
- Bumped Sphinx `version`/`release` to `0.2.9.8` to match `pyproject.toml`.

## [0.2.9.6] - 2026-04-28

### Fixed 🔧
- Synced `discord.py` minimum version across `requirements.txt` and `pyproject.toml` (>=2.7.1).
- Fixed critical `OPENAI_API_KEY` environment variable leak into `test_config.py` via autouse monkeypatch fixture.
- Fixed `CircuitBreaker` race condition under concurrent async load by adding state-transition lock.
- Fixed duplicate conversation history when OpenAI falls back to Perplexity after web-incapable responses.
- Fixed bare `except Exception` in `perplexity_processing.py` to specific exception types.
- Fixed missing `timeout=30` in `check_perplexity_health()` to match OpenAI health check parity.
- Fixed stale Python version references across all documentation (3.10 → 3.12).
- Fixed unterminated Mermaid diagram in `docs/HybridMode.md`.
- Fixed duplicate `MAX_HISTORY_PER_USER` key in `docs/HybridMode.md` config example.
- Fixed stale CI comment claiming Python 3.10 support.
- Fixed `PLR0911` mention in docs that was not reflected in `pyproject.toml`.

### Changed 🔁
- Unified coverage fail-under gate to **84%** in `pyproject.toml`.
- Centralized constants in `main.py` to import from `config.py`.
- Centralized link counting in `message_splitter.py` to use `LINK_PATTERN`.
- Pre-compiled regex patterns where possible.
- Standardized error messages in `message_processor.py` to import from `config.py`.
- Replaced per-call `secrets.SystemRandom()` with module-level instance in `error_handling.py`.
- Deduplicated `send_split_message` smoke tests between `test_bot.py` and `test_message_splitting.py`.
- Removed dead code across `perplexity_processing.py` and test files.
- Updated `.pre-commit-config.yaml` to latest `black` and `ruff` versions.
- Removed non-existent `.secrets.baseline` reference from detect-secrets hook.

### Security 🛡️
- Hardened `Dockerfile` with non-root `appuser`.
- Moved `config.ini` exclusion to `.dockerignore`.
- Prevented API key exposure in test output via environment isolation fixture.

### Tests ✅
- Added autouse env-isolation fixture to `test_config.py`.
- Converted `asyncio.run()` anti-patterns to native `pytest.mark.asyncio` tests.
- Replaced manual `sys.argv` mutation in `test_main.py` with `monkeypatch`.
- Added shared mock fixtures to `tests/conftest.py`.
- Removed dead constants, commented pseudocode, and redundant test coverage.

### Documentation 📝
- Updated README Discord.py badge to 2.7.1.
- Updated coverage target references from 80% to 84% in `docs/Architecture.md`.
- Corrected test file reference in `docs/Architecture.md`.
- Removed stale `PLR0911` and flake8/isort references.
- Rewrote `docs/Python_Versions.md` to reflect Python 3.12+ exclusivity.
- Aligned `docs/Security.md`, `docs/Setup.md`, `docs/API_Validation.md`, and `CONTRIBUTING.md` to current Python and package versions.

## [0.2.9.5] - 2026-02-28

### Added ✨
- **Smart Routing Overhaul** ✨: Comprehensive improvements to `src/smart_orchestrator.py` and `src/config.py` to better classify queries and route between OpenAI and Perplexity. Key capabilities:
  - Routing-only Discord markup sanitization to avoid mutating history, cache keys, logs, or API payloads.
  - Persona-agnostic OpenAI web-inability detection (regex patterns) to automatically reroute responses that state they "can't browse" or "don't have access to the internet".
  - Explicit `SEARCH_INTENT_PATTERNS` expanded to capture phrases like "the web", "the internet", "search online", and related user intents.
  - Routing telemetry helper that surfaces the trigger labels used for routing decisions (logged for observability).

### Fixed 🔧
- **Bidirectional Fallbacks** 🔁: Implemented safe fallback chaining and degraded responses so both directions now fall back appropriately: Perplexity→OpenAI and OpenAI→Perplexity with clear logging and a final degraded response if both fail.
- **Perplexity History Persistence** 🧾: Ensure Perplexity user messages are persisted in conversation history only after a successful Perplexity response (parity with OpenAI) to avoid storing failed/timed-out turns.
- **Time-sensitivity False Positives** ⚠️: Removed overly-broad standalone tokens (e.g., `\\bnow\\b`) and tightened `TIME_SENSITIVITY_PATTERNS` to reduce false positives.
- **Entity & Factual Pattern Tightening** 🔎: Narrowed entity detection (proper names, stock tickers) to reduce noisy web-routing from short/all-caps tokens.

### Changed 🔁
- **Docs & Diagrams** 📝: Updated Mermaid diagrams and `docs/HybridMode.md`, `docs/Architecture.md`, and README references to reflect the new routing flow and fallback behavior.
- **Docstrings & Developer Guidance** 📚: Added Google-style docstrings for touched public functions and updated `.github/copilot-instructions.md` with the enforced test/lint sequence and Python 3.12 guidance.
- **CI / Docker** 🐳: Aligned CI and Docker to Python 3.12: `Dockerfile` base image bumped to `python:3.12-slim-bookworm`, `pyproject.toml` `requires-python` set to `>=3.12`, and GitHub Actions primary CI now requires Python 3.12 (`.github/workflows/ci.yml`).

### Tests ✅
- Added and updated unit tests covering routing sanitization, OpenAI web-inability reroute, search-intent recognition, follow-up/conversational detection, entity pattern tightening, Perplexity persistence behavior, and routing trigger logging assertions.
- Full test run: `tox -e py312` — **583 passed**, coverage **86.36%** (threshold 84%).

- CI & Coverage: Guard Codecov uploads for PRs lacking repository secrets (forked PRs), and added a unit test covering the new `asyncio.timeout` branch in `src/web_scraper.py` to avoid tokenless upload failures causing CI to appear broken.

### Notes ⚠️
- No user-facing API changes to bot commands. Breaking change for contributors/CI: development and CI now target Python 3.12; update local environments accordingly.

### Breaking Change ❗️🐍
- **Dropped support for Python 3.10 and 3.11**: This release requires **Python 3.12 or newer**. CI, Docker, linters, and packaging have been updated to target `py312` as the minimum supported interpreter. If you're running this project locally on 3.10/3.11, please upgrade your interpreter or use a compatible environment. Update any deployment runners and CI configurations accordingly.

## [0.2.9] - 2026-02-26

### Fixed
- **Docker Versioned Tags**: Fixed Docker workflow to use `metadata-action` outputs instead of hardcoded `:latest`, so tag pushes now produce both versioned (`v0.2.9`) and `latest` images on GHCR and Docker Hub.
- **Docker Manual Rebuild**: Added `workflow_dispatch` trigger to the Docker workflow for on-demand rebuilds of any branch or tag.
- **Embed Continuations**: Align long embed splits with code-block-safe boundaries to prevent duplicated or dropped content in follow-up messages.
- **Web Scraper Retries**: Stop retry loops on non-HTML or oversized responses by treating them as terminal conditions.
- **Channel Mentions**: Strip Discord mentions before constructing channel `AIRequest` payloads to keep prompts and logs clean.
- **Regression Coverage**: Added tests for embed continuation alignment, scraper non-HTML sentinel handling, and channel mention cleaning.

### Added
- **Copilot/Codex Instructions**: New `.github/copilot-instructions.md` outlining the full terminal suite (`tox -e`, `black --check .`, `ruff check .`), Python 3.12 focus, and assistant guardrails.
- **Developer Note**: `docs/Development.md` now points AI assistants to the canonical test commands and Python 3.12 target.

### Added
- **Major Python Architecture Restructure**: Consolidated legacy fixes into a unified release. De-coupled the monolithic `bot.py` into distinct single-responsibility components (`message_router.py`, `message_processor.py`, `message_splitter.py`, `bot_manager.py`).
- **Enhanced Test Coverage**: Added regression tests for message routing (DM vs channel handling, self-ignore, error notify) and bot manager lifecycle (presence, signal handlers, graceful shutdown). Suite now runs 553 tests at ~86.8% coverage with zero warnings.
- **Lazy Logging Framework**: Standardized application to use lazy evaluation strings (`%s`/`%d`) for all logging calls to massively improve latency and adhere to production best practices.
- **Pytest Warning Guardrail**: Added a dedicated `tests/conftest.py` and matching `pyproject.toml` filter to suppress the upstream `discord.player` `audioop` deprecation so `-W error` runs remain green on Python 3.12+.
- **Frontier Model Validation Helper**: Introduced `is_supported_openai_model()` with GPT-5 snapshot support to centralize validation across health checks, API validation, and builders.
- **Conversational UX Polish**: Added Discord typing indicators during AI processing, enforced reply-to threading for all responses, and prefixed responses with the requesting user's mention for more conversational replies.

### Changed
- **Coverage Gates**: Raised coverage enforcement to 84% across tox and Codecov (matching README/testing guidance).
- **Security Audits**: Added `pip-audit` to the standard toolchain to keep dependency issues visible during local runs.
- **README Badges**: Added per-Python test badges with `py312` marked required (py311/py310 optional) and reorganized badge layout for better desktop/mobile wrapping.
- **Dependencies**: Upgraded various Python packages to their latest stable environments across `requirements.txt`, `pyproject.toml`, and `.pre-commit-config.yaml`:
  - `openai` (>=2.24.0)
  - `websockets` (>=16.0)
  - `black` (>=26.1.0)
  - `ruff` (>=0.15.4)
  - `pytest` (>=9.0.2)
  - `coverage[toml]` (>=7.13.4)
  - `tox` (>=4.46.3)
  - `pre-commit` (>=4.5.1)
- **Formatting**: Systematic cleanup of all code style inconsistencies, suppressing magic values, resolving long-line overlaps cleanly, and enforcing strict "zero-warn" no-ignore strategies.
- **Architectural Cleanup**: Removed circular dependencies passing around the global `bot` context and gracefully transitioned to explicit Dependency Injection (`deps`) flow.
- **Perplexity Inline Citations**: Refactored the core embedding logic making Perplexity links neatly formatted inline clickable hyperlink citations `[[1]](url)` directly within the Discord Embed.
- **Warnings Mitigation**: Cleanly silenced upstream layer warnings within the `[tool.pytest.ini_options]` (e.g., the `audioop` DeprecationWarning from `discord.py`) to keep CI/CD pipelines crisp.
- **Documentation Overhaul**: Modernized all references inside `Architecture.md` and filled missing docstring constraints (`D10x` compliant) across every Python module.
- **Frontier-Only AI Configuration**: Standardized defaults to GPT-5 + Sonar-Pro, removed unsupported temperature parameters for GPT-5 and Perplexity, and updated validation messaging accordingly.
- **Docs & README Refresh**: Rebuilt `README.md` into a concise quick-start with deep links to `docs/` sections, refreshed `OpenAI`, `Perplexity`, `HybridMode`, `Architecture`, and `API_Validation` guides to reflect new guardrails and diagrams.
- **Test Suite Updates**: Updated OpenAI/Perplexity builder tests to target GPT-5 defaults, removed temperature expectations, and ensured model validation coverage for GPT-5 snapshots.
- **Security**: Pinned `aiohttp>=3.13.3` to resolve upstream CVEs flagged by Dependabot (GHSA-3pmm-p7ch-p9vm family) and pip-audit.
- **Lint & Format Enforcement**: Verified `ruff check --show-fixes .` and `black --check .` are clean alongside `tox`.

## [v0.2.8.1] - 2026-01-06

### Fixed
- **🧪 Test Coverage**: Enhanced coverage for critical AI processing modules to >80%
  - `src/perplexity_processing.py`: Improved to 89% coverage (URL scraping failures, timeouts, legacy citation fallback)
  - `src/smart_orchestrator.py`: Improved to 88% coverage (consistency overrides, hybrid fallback chains)
  - Fixed logic bug in legacy citation extraction when API metadata is missing
- **🔧 Code Quality**: Standardized linting configuration
  - Unified `tox.ini` and `pyproject.toml` configuration for `ruff` and `black` to ensure single source of truth
  - Fixed unused variable warnings in test suite

### Changed
- **Testing Infrastructure**: Robust mock usage
  - Implemented correct `AsyncMock` patterns for async orchestrator tests

## [v0.2.8.0] - 2025-12-04

### Added
- **🔐 Security Enhancements**: Comprehensive security improvements
  - Dependency vulnerability scanning with `pip-audit` in CI/CD pipeline
  - GitHub Dependabot configuration for automated dependency updates
  - API key format validation with clear error messages and help links
  - Pre-commit hooks with `detect-secrets`, `black`, and `ruff`
  - Log sanitization to prevent API key exposure (fixes CodeQL alert)
  - Custom CodeQL workflow with v4 actions and false-positive filtering
  - Dependency Review action for PR vulnerability scanning
  - Copilot Review auto-request for all PRs
  - Enhanced sanitization: hex secrets, JWT tokens, API keys redacted at source
- **📖 Documentation**: New comprehensive documentation
  - `docs/Architecture.md` - System design, components, request flow diagrams, design patterns
  - `docs/Security.md` - API key management, rate limiting, input validation, Docker hardening
  - Updated documentation index with new guides
  - Added comprehensive README badges (CI, coverage, Python, code style, integrations, security)
- **📦 Package Improvements**: Modern Python packaging
  - `src/__init__.py` with proper package exports and metadata
  - `src/py.typed` marker for PEP 561 type hints support
  - Module docstrings added to `bot.py` and `config.py`
- **🧪 Test Coverage**: Comprehensive testing (545+ tests, 80.80% coverage)
  - Configuration edge cases (malformed files, invalid values, unicode)
  - API validation tests (40+ cases including key format validation)
  - Error recovery tests (circuit breaker, retry logic)
  - Message splitting tests (unicode, emoji, code blocks)
  - Load/stress tests (10k+ concurrent users, thread safety)

### Fixed
- **🐛 Signal Handler**: Fixed graceful shutdown crash on SIGTERM
  - Eliminated "Cannot run the event loop while another loop is running" error
  - Now raises KeyboardInterrupt for proper discord.py cleanup
- **🔑 API Key Validation**: Relaxed overly strict format patterns
  - Supports modern OpenAI formats: `sk-proj-xxx`, `sk-svcacct-xxx`
  - Updated regex to allow hyphens/underscores in key body
- **🔧 Code Quality**: Fixed 26 ruff lint errors
  - Cleaner exception handling with `contextlib.suppress()`
  - More specific exception catches (no blind `Exception`)
  - Removed duplicate methods, fixed unused variables
- **📄 Documentation**: Fixed broken links and outdated references
  - Fixed 16 broken documentation links
  - Updated GPT-4 references to GPT-5 series throughout

### Changed
- **🚀 CI/CD**: Modernized GitHub Actions workflow
  - Upgraded actions (setup-python@v5, cache@v4, codecov@v4)
  - Added concurrency control to cancel stale runs
  - Added job timeouts (15min tests, 5min lint/security)
  - Python 3.11/3.12 compatibility testing (informational, non-blocking)
  - Simplified lint job, fixed security scan dependency installation
  - Added Dependency Review action (required, blocks PRs with vulnerabilities)
  - Added Copilot Review auto-request (optional, informational)
- **🐍 Python Compatibility**: Expanded version support
  - Changed `requires-python` from `==3.10.*` to `>=3.10`
  - Supports Python 3.10, 3.11, 3.12 and future versions
- **⬆️ Dependencies**: Upgraded to latest bleeding edge versions
  - discord.py 2.6.4, openai 2.8.1, requests 2.32.5, beautifulsoup4 4.14.3
  - black 25.11.0, ruff 0.14.7, pytest 9.0.1, tox 4.32.0
  - Full list: httpx 0.28.1, pytest-asyncio 1.3.0, coverage 7.12.0, pip-audit 2.10.0
- **🧹 Configuration**: Consolidated tool configuration
  - Removed redundant `pytest.ini` and `.flake8` (now in `pyproject.toml`)
  - Consolidated constants into `config.py` (single source of truth)
- **🛡️ Reliability**: Enhanced stability and monitoring
  - Graceful shutdown with signal handlers (SIGTERM, SIGINT)
  - Connection pool health monitoring and status checks
  - Memory usage statistics in conversation manager
- **⚙️ Infrastructure**: Improved Docker healthcheck
  - Validates bot configuration on startup, not just Python import

### Removed
- Redundant test files: `test_config_basic.py`, `test_bot_basic.py`
- Redundant config files: `pytest.ini`, `.flake8`

## [v0.2.7.2] - 2025-01-23

### Fixed
- **Message Splitting Improvements**: Enhanced message splitting with recursion limit protection
  - Fixed HTTPException 400 Bad Request for messages exceeding Discord's 2000-character limit
  - Implemented proper recursion limit handling with graceful fallback
  - Added comprehensive message splitting test suite (26 test cases)
  - Ensured all message parts respect Discord's character limits
  - Preserved content integrity during splitting process
  - Added proper error handling and logging for recursion scenarios

### Added
- **Comprehensive Test Coverage**: New `tests/test_message_splitting.py` with 26 test cases
  - Basic message splitting functionality tests
  - Code block splitting tests
  - Integration tests for long messages
  - Edge case testing (empty messages, unicode, extreme lengths)
  - Recursion limit and truncation behavior tests
  - Content preservation verification

### Documentation
- **Enhanced Message Splitting Guide**: Updated `docs/MessageSplitting.md`
  - Added recursion limit protection section
  - Added troubleshooting for new features
  - Included Mermaid diagrams for recursion flow

## [v0.2.7.1] - 2025-09-23

### Fixed
- **HTTP/2 Dependency Issues**: Fixed production environment HTTP/2 fallback to HTTP/1.1
  - Updated `httpx[http2]>=0.28.0` and `h2>=4.3.0` in `requirements.txt`
  - Added HTTP/2 dependencies to `pyproject.toml` for consistency
  - Enhanced `docs/ConnectionPooling.md` with version requirements and troubleshooting guide
  - Resolved issue where httpx 0.25.1 had unreliable HTTP/2 support causing fallback

### Documentation
- **Connection Pooling Guide**: Added comprehensive troubleshooting section for HTTP/2 issues
- **Version Requirements**: Documented minimum versions for reliable HTTP/2 operation
- **Installation Commands**: Updated with specific version requirements

## [v0.2.7] - 2025-01-23

### Added
- **HTTP/2 Connection Pooling**: Optimized API client performance with configurable connection pools
  - `src/connection_pool.py` - Centralized connection pool management for OpenAI and Perplexity APIs
  - API-specific connection limits: OpenAI (50 max, 10 keepalive), Perplexity (30 max, 5 keepalive)
  - HTTP/2 support for improved throughput and multiplexed connections
  - Configurable via `config.ini` with `[ConnectionPool]` section
- **Enhanced Documentation**: Comprehensive connection pooling guide in `docs/ConnectionPooling.md`

### Changed
- **Conversation Management**: Streamlined conversation handling architecture
  - Removed redundant `src/conversations.py` module (functionality consolidated into `ThreadSafeConversationManager`)
  - Fixed conversation summary consistency across all operation modes (OpenAI-only, Perplexity-only, Hybrid)
  - Updated hybrid mode to use passed `conversation_summary` parameter consistently
- **Code Quality**: Improved codebase maintainability
  - Removed duplicate test files (`test_conversations.py`, `test_get_conversation_summary.py`)
  - Updated documentation to reflect current architecture
  - Enhanced test coverage for conversation management

### Fixed
- **Conversation Summary Consistency**: Fixed hybrid mode to use passed conversation summary parameter
- **Documentation Accuracy**: Updated CHANGELOG and documentation to reflect current file structure
- **Code Formatting**: Applied consistent black and ruff formatting across all files

### Performance
- **API Overhead Reduction**: Connection pooling reduces connection establishment overhead
- **Memory Efficiency**: Supports 10k+ users with <100MB conversation memory
- **Rate Limit Compliance**: Optimized connection pools respect API rate limits

## [v0.2.6] - 2025-01-25

### Fixed
- **🔗 Citation Hyperlinks**: Fixed Perplexity citations not rendering as clickable links in Discord
  - **Root Cause**: Discord only supports `[text](url)` hyperlinks in embeds, not regular messages
  - **API Discovery**: Perplexity API now provides citations in `citations` metadata field, not inline URLs
  - **Solution**: Implemented Discord embeds with citation metadata extraction for proper hyperlink formatting
  - **Result**: Citations now appear as clickable hyperlinks: `[[1]](https://source.com)`
- **📱 Message Splitting with Embeds**: Enhanced message splitting to properly handle Discord embeds
  - Embed with citations attached to first message part
  - Continuation messages sent as plain text
  - Preserves citation accessibility for long responses

### Added  
- **`CitationEmbedFormatter` Class**: New utility for creating Discord embeds with properly formatted citations
- **Enhanced Citation Processing**: Modern Perplexity API support with `citations` and `search_results` metadata extraction
- **Comprehensive Citation Tests**: 17 new tests covering end-to-end citation functionality
- **Debug Scripts**: Added `/scripts` folder with debugging utilities for citation testing
- **Smart Embed Decision Logic**: Automatically determines when to use embeds vs plain text

### Changed
- **Perplexity Response Format**: Now returns `(text, suppress_embeds, embed_data)` tuple
- **Citation Extraction**: Updated to use Perplexity API metadata fields instead of inline URL parsing
- **Message Sending Pipeline**: Updated to handle both text messages and embeds seamlessly  
- **Citation Display**: Citations only appear in embeds for Perplexity responses (OpenAI remains plain text)
- **Dependencies**: Updated to `discord.py>=2.6.2` and `openai>=1.101.0`

### Technical Details
- **Modern API Support**: Handles both `citations` array and `search_results` objects from Perplexity API
- **Discord Embed Limits**: Properly handles 4096 character description limit
- **Backward Compatibility**: Non-citation responses continue using plain text
- **Error Handling**: Graceful fallback to plain text if embed creation fails
- **Performance**: Maintains existing caching and deduplication optimizations

## [v0.2.5] - 2025-08-10

### Added
- **Extended Python Version Support**: Added official support for Python 3.10 only
- **GPT-5 Model Family**: Complete migration to GPT-5 variants (gpt-5, gpt-5-mini, gpt-5-nano, gpt-5-chat)
- **Smart AI Orchestration**: Intelligent routing between OpenAI and Perplexity based on query analysis
- **Thread-Safe Conversation Management**: Robust conversation history with metadata tracking
- **Comprehensive Error Handling**: Circuit breaker pattern, exponential backoff, and graceful degradation
- **Health Monitoring**: Real-time API health checks and performance metrics
- **Advanced Caching**: Response caching with TTL and request deduplication
- **Rate Limiting**: Per-user rate limiting with configurable thresholds
- **Message Processing**: Intelligent message splitting and Discord formatting
- **API Validation**: Startup parameter validation and configuration checks
- **Performance Monitoring**: Built-in performance tracking and optimization
- **Tox Multi-Version Testing**: Comprehensive testing with Python 3.10

### Changed
- **Linting Workflow**: Streamlined from 4 tools (isort + black + ruff + flake8) to 2 tools (black + ruff)
- **GPT Model Default**: Changed from gpt-4o-mini to gpt-5-mini for cost-effectiveness
- **Model Validation**: Updated to support new GPT-5 model family
- **CI/CD Pipeline**: Enhanced GitHub Actions with multi-version testing matrix
- **Configuration Management**: Centralized constants and improved validation
- **Error Recovery**: Enhanced retry logic and user-friendly error messages
- **Conversation Handling**: Improved context management and summarization
- **Documentation Structure**: Reorganized and expanded documentation with new guides and examples

### Technical Improvements
- **Type Annotation Compatibility**: Ensured all modern type hints work across supported Python versions
- **Dependency Compatibility**: Verified all dependencies work with supported Python versions
- **Testing Matrix**: Comprehensive testing across all supported Python versions
- **Code Quality**: Removed unused variables, cleaned up deprecated parameters
- **Performance**: Pre-compiled regex patterns and optimized data structures
- **Memory Management**: Efficient conversation pruning and cleanup
- **Async Operations**: Proper async/await patterns throughout codebase
- **Security**: Input sanitization and Discord markdown protection
- **Logging**: Structured logging with configurable levels and file output
- **Testing**: 25+ integration tests with comprehensive coverage

### Fixed
- **OpenAI API 400 Error**: Resolved by using supported GPT-5 model variants
- **Linting Conflicts**: Eliminated endless loop between isort and ruff
- **Test Failures**: Fixed all test failures related to GPT-5 model migration
- **Documentation**: Updated all model cards and configuration examples
- **CI Failures**: Resolved all GitHub Actions workflow issues
- **Code Comments**: Cleaned up leftover development comments and unused code
- **Parameter Validation**: Fixed API parameter validation for new models

## [v0.2.0] - 2025-07-16

### Added
- **Major Python Architecture Restructure** ([#180](https://github.com/johndotpub/DiscordianAI/pull/180)): Complete modularization from monolithic `bot.py` (+1,585 −531 lines)
- **Modular Package Structure**: Reorganized into standard Python package layout under `src/` directory:
  - `src/bot.py` - Main bot logic with modular dependencies and event handlers
  - `src/config.py` - Configuration management with hierarchical loading (CLI > env > defaults)
  - `src/conversation_manager.py` - Thread-safe conversation history management and summarization
  - `src/discord_bot.py` - Discord-specific utilities like activity status setting
  - `src/openai_processing.py` - OpenAI API interaction and message processing
  - `src/rate_limits.py` - Rate limiting functionality for user requests
  - `src/main.py` - Entry point with global exception handling and configuration loading
  - `src/__init__.py` - Package initialization
- **Enhanced CLI Support**: New `--folder` argument for base directory support with relative config/log resolution
- **Comprehensive Test Suite**: Full async testing capabilities with pytest-asyncio
  - Robust async tests for OpenAI processing including edge cases and error handling
  - Comprehensive test coverage for all modules (config, main, discord_bot, conversation_manager)
  - Modern testing patterns with dependency injection and realistic fake clients
- **Development Tooling**: Modernized development environment
  - Added `.flake8` and `pytest.ini` configuration files for consistency
  - PEP 621 compliant `pyproject.toml` with proper dev dependencies
  - Updated `tox.ini` for streamlined testing and environment management
  - Aligned black and ruff configurations (resolved E203, W503 conflicts)

### Changed
- **Complete Codebase Restructure**: Transformed from monolithic architecture to modular design
- **Configuration System**: Hierarchical configuration loading (CLI arguments > environment variables > defaults)
- **Error Handling**: Enhanced with global exception handler in main entry point for robust error logging
- **Code Quality**: Achieved full PEP8 compliance and reduced cyclomatic complexity
- **Testing Infrastructure**: Migrated to modern async testing patterns with comprehensive coverage
- **Documentation**: Updated and expanded documentation for new CLI, configuration hierarchy, and project structure
- **Packaging**: Modernized Python packaging standards with clean separation of runtime vs dev dependencies

### Fixed
- **Cyclomatic Complexity**: Refactored `run_bot` and message processing to reduce complexity and improve maintainability
- **Import Management**: Corrected all import paths and module references for new structure
- **Code Standards**: Fixed all flake8 errors (E203, E301, E302, E306, E501) and unused imports
- **Function Spacing**: Ensured proper blank lines before top-level functions for PEP8 compliance
- **Error Handling**: Improved robustness in message processing and OpenAI API calls with comprehensive try/catch blocks
- **Test Reliability**: Updated all tests for new modular layout ensuring 100% pass rate in CI
- **Daemon Compatibility**: Updated `discordian.sh` script to use modular entry point (`src/main.py`)

## [v0.1.9] - 2025-06-11

### Changed
- Upgraded OpenAI library to version 1.84.0
- Updated pytest to 8.4.0 for improved testing capabilities
- Enhanced dependency management with automated dependabot updates

### Added
- Combined pull request workflow for efficient dependency management
- Improved CI/CD pipeline with PR combination support

### Fixed
- Multiple dependency version bumps for security and compatibility
- Enhanced flake8 linting with version 7.2.0
- Updated pyflakes to 3.3.2 for better code analysis

## [v0.1.8] - 2025-02-26

### Added
- Discord-compatible formatting enhancements to system prompt
- Improved bot personality with better Discord integration

### Changed
- Enhanced system message configuration for more natural Discord interactions
- Updated OpenAI library through multiple version increments (1.61.x to 1.64.0)
- Improved websockets support with version 15.0 compatibility

### Fixed
- Better Discord message formatting and response handling
- Enhanced compatibility with Discord's markdown and formatting systems

## [v0.1.7] - 2024-04-19

### Added
- **Docker Support**: Complete containerization with Dockerfile and docker-compose
- GitHub Container Registry (GHCR) publishing workflow
- Enhanced Docker image optimization and performance improvements

### Changed
- **Breaking Change**: Python version support simplified to 3.10 only
- Improved Dockerfile compatibility across different environments
- Enhanced security by ensuring config.ini exclusion from Docker images
- Updated OpenAI library to version 1.17.1
- Modernized README.md with better documentation structure

### Fixed
- Docker workflow placement and configuration issues
- Enhanced container build process for better performance
- Improved dependency management in containerized environments

## [v0.1.6] - 2024-02-19

### Added
- **Docker Support**: Initial Docker implementation with Dockerfile
- Issue templates for better bug reporting and feature requests
- GitHub issue template structure for streamlined contributions
- Enhanced project documentation and contribution guidelines

### Changed
- Improved repository structure with better organization
- Updated dependency management with multiple library upgrades
- Enhanced testing framework with pytest 8.0.0 compatibility

### Fixed
- Resolved typing system changes and compatibility issues
- Fixed various dependency conflicts and version mismatches
- Improved error handling and stability

## [v0.1.5] - 2024-02-02

### Added
- **Message Splitting**: Automatic splitting of long responses to respect Discord's 2000-character limit
- Intelligent message splitting that preserves code blocks and formatting
- Enhanced logging system with better error tracking and debugging

### Fixed
- **Session Handling**: Major improvements to conversation session management
- Resolved issues with conversation history persistence
- Better handling of user session data across bot restarts

### Changed
- Improved response handling for better user experience
- Enhanced error recovery and graceful degradation
- Updated OpenAI library to version 1.10.0

## [v0.1.2] - 2024-01-07

### Added
- **Daemon Control Script**: `discordian.sh` bash script for production deployment
- Process management with automatic termination of existing instances
- Configurable daemon mode with background execution support
- Enhanced logging with timestamps and structured output
- **CI/CD Pipeline**: Complete GitHub Actions workflow setup
  - Automated testing with pytest
  - Code quality checks with flake8
  - Dependency security scanning
- **Dependency Management**: Automated dependency updates via dependabot
- Enhanced `.gitignore` for better development experience

### Changed
- Improved configuration handling and validation
- Enhanced error checking with pipeline failure detection
- Updated multiple dependencies for security and performance
- Better documentation with workflow badges

### Fixed
- Resolved flake8 compliance issues and code quality improvements
- Fixed Python package compatibility issues
- Enhanced stability and reliability of daemon operations

## [v0.1.1] - 2023-06-14

### Added
- **Unit Testing Framework**: Comprehensive test suite with pytest
- Code quality enforcement with flake8 linting
- Automated testing pipeline integration
- PEP8 compliance improvements across codebase

### Changed
- Reformatted entire codebase to align with PEP8 standards
- Enhanced code quality and maintainability
- Improved development workflow with testing automation

### Fixed
- Code style consistency issues
- Python formatting and structure improvements

## [v0.1.0] - 2023-06-06

### Added
- **Initial Release**: Complete Discord bot implementation
- OpenAI GPT API integration for intelligent responses
- Discord.py framework integration with modern async/await patterns
- Configuration management via INI files with environment variable support
- Rate limiting system to prevent spam and API abuse
- Conversation history tracking for context-aware responses
- Direct message and channel mention support
- Configurable bot presence and activity status
- Global exception handling for robust error management
- Shard support for scalability
- Comprehensive logging system
- Flexible deployment with command-line configuration options

### Features
- **Multi-Channel Support**: Configurable channel allowlist for targeted bot responses
- **Conversation Context**: Persistent conversation history per user for meaningful interactions
- **Rate Limiting**: Configurable rate limits to prevent abuse (default: 10 messages per 60 seconds)
- **Message Handling**: Support for both direct messages and channel mentions
- **Error Recovery**: Graceful error handling with detailed logging
- **Deployment Flexibility**: Support for custom configuration files and base folders
