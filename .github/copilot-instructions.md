# Copilot / Codex Instructions

This repository targets **Python 3.12**. Legacy 3.10/3.11 support is minimal; do not downgrade tooling or targets.

## Full Test Suite (run in terminal)
- `tox -e py312`
- `black --check .`
- `ruff check .`
- `pip-audit`

Always run the above in a terminal before finishing work or updating PRs. Do not skip or substitute other runners.

## Working Loop for Assistants
1. Read the task and confirm scope; avoid reverting user changes.
2. Plan briefly; prefer multiple commits for edits.
3. Make changes; keep ASCII unless the file already uses non-ASCII.
4. Run the full suite (commands above) in the terminal, in order.
5. Summarize changes and test results; keep existing PR comment structure when updating PRs.

## PR & Changelog Hygiene
- When the changelog is updated, refresh the active PR description to include the new items without removing existing details.
- Keep release-note bullets and PR body aligned before finishing work.
- We like to use emojis in our PR comments and changelog for quick scanning; preserve them when updating PRs.

## Guardrails
- Never commit secrets or config files with credentials (e.g., `config.ini`).
- Avoid destructive git commands (`reset --hard`, force pushes) unless explicitly asked.
- Align with CI: tox/black/ruff/pip-audit are required; CodeQL runs separately; Docker builds run only on main/tags.
- Use Python 3.12 for local runs; do not adjust `target-version` settings downward.

## Quality Gates
- Keep coverage at or above 84% (Codecov and tox gate); call out any drops and add tests.
- Update the changelog for user-visible changes; do not skip release notes.
- Preserve the PR comment layout (including emojis/headings) and list commands + results.
- Commit frequently with small, reviewable chunks; avoid large unreviewable drops.
- Re-scan Copilot findings before finalizing to ensure nothing was missed.

## Commit Messages
- Use conventional prefixes (feat/fix/docs/chore/test/etc.) with a useful emoji.
- Keep commits concise for quick review; reserve the richer detail for the PR description.
- Start the body with a TL;DR line, then bullet the key changes; add Security and Breaking Change sections when relevant.

## Useful Paths
- Full suite commands are defined here; surface them proactively in chats.
- Developer workflow details live in `docs/Development.md` (see the AI assistants note).
