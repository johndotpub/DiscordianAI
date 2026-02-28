# Copilot / Codex Instructions

This repository targets **Python 3.12**. Legacy 3.10/3.11 support is minimal; do not downgrade tooling or targets.

## Full Test Suite (run in terminal)
- `tox -e py312`
- `black --check .`
- `ruff check .`
- `tox -e audit`

Always run the above in a terminal before finishing work or updating PRs. Do not skip or substitute other runners.

## Working Loop for Assistants
1. Read the task and confirm scope; avoid reverting user changes.
2. Plan briefly; prefer multiple commits for edits.
3. Make changes; keep ASCII unless the file already uses non-ASCII.
4. Run the full suite (commands above) in the terminal, in order.
5. Summarize changes and test results; keep existing PR comment structure when updating PRs.

## Code Standards

### Type Hints
- Use modern syntax: `str | None`, `list[dict[str, str]]`, `dict[str, Any] | None`.
- Do not use `typing.Union`, `typing.Optional`, or `typing.List` — these are legacy.
- Annotate all public function signatures (parameters + return types).

### Docstring Standards
- All public functions and classes **must** have full Google-style docstrings (`Args`, `Returns`, `Raises`).
- Private helpers (`_` prefix) **must** have at minimum a summary line; add `Args`/`Returns` when non-trivial.
- Reference standard: `src/conversation_manager.py` (gold-standard example in this repo).
- Ruff enforces pydocstyle `D` rules with `convention = "google"` — validate with `ruff check .`.
- When touching any function, audit and upgrade its docstring to full Google-style before finishing.

### Immutable Data
- Use frozen dataclasses (`@dataclass(frozen=True)`) for request/config objects — never mutate after construction.
- Configuration and compiled regex patterns live in `src/config.py` (single source of truth).

### Error Handling
- Use structured error handling from `src/error_handling.py` — not bare `try/except Exception`.
- Wrap API calls with `RetryConfig`-based retry logic.
- Always provide degraded fallback rather than hard failure when reasonable.

### Async Patterns
- All Discord event handlers and API call paths are `async`.
- Use `aiohttp`/`httpx` for HTTP — never blocking `requests` in async code paths.
- Thread-safe conversation manager uses `threading.Lock` — respect lock ordering.

## Pattern & Regex Conventions
- All routing/detection patterns are compiled in `src/config.py` as `COMPILED_*` constants.
- Use `re.IGNORECASE` on new text-matching patterns unless case sensitivity is intentional and documented.
- Test patterns with both positive and negative cases; false positives are worse than false negatives in routing.

## Caching & Deduplication
- `cached_response` and `deduplicated_request` decorators in `src/caching.py` wrap processing functions.
- Cache keys derive from `request.message` — never sanitize or transform the message before it reaches cache/API.
- TTL and LRU size are configured in `config.ini`; do not hardcode cache parameters.

## PR & Changelog Hygiene
- When the changelog is updated, refresh the active PR description to include the new items without removing existing details.
- Keep release-note bullets and PR body aligned before finishing work.
- We like to use emojis in our PR comments and changelog for quick scanning; preserve them when updating PRs.

## Guardrails
- Never commit secrets or config files with credentials (e.g., `config.ini`).
- Avoid destructive git commands (`reset --hard`, force pushes) unless explicitly asked.
- Align with CI: tox/black/ruff/pip-audit are required; CodeQL runs separately; Docker builds run only on main/tags.
- Use Python 3.12 for local runs; do not adjust `target-version` settings downward.
- Do not add `# noqa`, `# type: ignore`, or `# pragma: no cover` without a justifying comment.

## Quality Gates
- Keep coverage at or above 84% (Codecov and tox gate); call out any drops and add tests.
- Update the changelog for user-visible changes; do not skip release notes.
- Preserve the PR comment layout (including emojis/headings) and list commands + results.
- Commit frequently with small, reviewable chunks; avoid large unreviewable drops.
- Re-scan Copilot findings before finalizing to ensure nothing was missed.
- `gh` CLI is available locally and auth-ready for updating PR bodies.

## Commit Messages
- Use conventional prefixes (feat/fix/docs/chore/test/etc.) with a useful emoji.
- Keep commits concise for quick review; reserve the richer detail for the PR description.
- Start the body with a TL;DR line, then bullet the key changes; add Security and Breaking Change sections when relevant.

## Testing Conventions
- Tests live in `tests/` and are exempt from docstring rules (ruff per-file-ignores).
- Use `pytest` fixtures from `tests/conftest.py` — prefer shared fixtures over inline setup.
- Mock external services (Discord, OpenAI, Perplexity) — never make real API calls in tests.
- Name test files `test_<module>.py` mirroring `src/<module>.py`.
- Both positive (happy path) and negative (error/edge) tests are required for new logic.

## Useful Paths
- Full suite commands are defined here; surface them proactively in chats.
- Developer workflow details live in `docs/Development.md` (see the AI assistants note).
- All routing patterns: `src/config.py`
- All data models: `src/models.py`
- Docstring reference: `src/conversation_manager.py`
