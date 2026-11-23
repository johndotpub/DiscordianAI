# Operational Scripts

Helper scripts for development, release checks, and troubleshooting. They are
developer tools, not part of the bot runtime.

## Available Scripts

### `preflight.sh`
Run every repository gate in order (black, ruff, pytest, Sphinx, wheel build) and
stop at the first failure.

```bash
bash scripts/preflight.sh
```

### `probe_providers.py`
Probe the configured OpenAI-compatible and Perplexity endpoints and print response
shapes without printing secrets. Credentials come from the environment.

```bash
OPENAI_API_KEY=... PERPLEXITY_API_KEY=... .venv/bin/python scripts/probe_providers.py
```

### `mutation_check.py`
Apply curated source mutations and verify that the named tests fail, guarding
against weakened coverage.

```bash
.venv/bin/python scripts/mutation_check.py
.venv/bin/python scripts/mutation_check.py --only cache-key
```

It requires a clean working tree for the mutation targets, then copies the checkout
(without `.git`, virtual environments, caches, logs, local `.ini` files, or `.env`)
into a scratch directory. Every mutation is written and tested there, so a killed or
failed run cannot leave the real source corrupted.

### `regen_golden.py`
Check golden-behaviour fixtures for drift, or rewrite them with `--write` and
`GOLDEN_REGEN=1`. Rewriting fixtures is a deliberate behaviour change.

```bash
.venv/bin/python scripts/regen_golden.py
GOLDEN_REGEN=1 .venv/bin/python scripts/regen_golden.py --write
```

### `router_eval.py`
Score the routing heuristic on a labelled JSONL corpus, overall and per slice.

```bash
.venv/bin/python scripts/router_eval.py --corpus corpus.jsonl [--json] [--slice FIELD]
```

It reads rows with `text`, `expect` (`web`, `local`, `ambiguous`), and optional
`slice` and `why`. Ambiguous rows are excluded and counted. The report starts with
recall and its 95% Wilson interval, then precision, accuracy, and per-slice
TP/FP/TN/FN counts; `--json` emits the same report.

### `launcher_lib.sh`
Process-management helpers sourced by `discordian.sh`: the restart wait, PID-file
cleanup, and config-scoped straggler lookup. It is not run directly; source it from
a bash test or the launcher.

## Usage Notes

- Scripts that need provider credentials read them from the environment or from an
  explicit config path; none ships a private config name or a credential.
- `mutation_check.py` and `regen_golden.py --write` modify files by design.
  `mutation_check.py` verifies and restores its targets; `regen_golden.py` rewrites
  fixtures only when explicitly asked. The other scripts are read-only.
- Keep generated logs, `.ini` files, and `.hermes/` state out of the repository;
  they are ignored by `.gitignore`.
- Use the project virtual environment at `.venv` so the scripts import the same
  dependencies as the test suite.

## Adding New Scripts

When adding a script:
1. Put a shebang and module docstring at the top.
2. Accept any configuration path as an argument or environment variable; never
   hardcode a deployment name.
3. Document it in this file, including what it reads and whether it writes.
