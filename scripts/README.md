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
