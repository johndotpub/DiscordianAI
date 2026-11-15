# Debug Scripts

This folder contains debugging utilities for DiscordianAI development and troubleshooting.

## Available Scripts

### `debug_perplexity_citations.py`
Debug Perplexity citation extraction with real API calls.

**Usage:**
```bash
python scripts/debug_perplexity_citations.py [config_file]
```

**Examples:**
```bash
# Use default config.ini
python scripts/debug_perplexity_citations.py

# Use custom config file
python scripts/debug_perplexity_citations.py my_bot.ini
```

**What it does:**
- Tests citation extraction with real Perplexity API
- Validates that citations are properly mapped to URLs
- Checks Discord embed formatting
- Shows detailed logging for debugging

**Requirements:**
- Valid Perplexity API key in config file
- Internet connection
- All project dependencies installed

### `router_eval.py`
Score the routing heuristic on a labelled JSONL corpus, overall and per slice.

**Usage:**
```bash
python scripts/router_eval.py --corpus corpus.jsonl [--json] [--slice FIELD]
```

**What it does:**
- Reads rows with `text`, `expect` (`web`, `local`, `ambiguous`), optional `slice` and `why`
- Excludes ambiguous rows and reports how many were excluded
- Prints recall first, with a 95% Wilson interval, then precision and accuracy
- Reports TP/FP/TN/FN for the whole corpus and for each slice
- With `--json`, emits the same report for CI

### `probe_providers.py`
Probe the configured OpenAI-compatible and Perplexity endpoints and print response shapes, never secrets.

### `mutation_check.py`
Apply curated source mutations and verify that the named tests fail, guarding against weakened coverage.

### `regen_golden.py`
Check golden-behaviour fixtures for drift, or rewrite them with `--write` and `GOLDEN_REGEN=1`.

### `preflight.sh`
Run every repository gate in order (black, ruff, pytest, Sphinx, wheel build) and stop at the first failure.

### Other Debug Scripts
Additional debugging utilities for response analysis and API testing.

## Usage Notes

- **Config Files**: Scripts accept any .ini config file with proper API keys
- **Private Configs**: Don't commit personal config files (like bender.ini) to the repo
- **Logging**: Scripts use DEBUG level logging for detailed output
- **Safety**: Scripts only read data, they don't modify anything

## Adding New Scripts

When adding new debug scripts:
1. Use `debug_` prefix for the filename
2. Accept config file as command line argument
3. Include proper error handling and logging
4. Document usage in this README
