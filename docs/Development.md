# Development Guide

This guide explains the modern development workflow for DiscordianAI using streamlined linting tools.

## Python Version Support

DiscordianAI officially supports **Python 3.10, 3.11, 3.12, and 3.13**. The codebase uses modern Python features including:

- **Generic Type Annotations** (Python 3.9+): `list[dict[str, str]]`, `dict[str, Any]`
- **Union Types with |** (Python 3.10+): `str | None`, `dict[str, Any] | None`
- **Dataclasses** (Python 3.7+): `@dataclass` decorators
- **Modern Type Hints**: No legacy `typing.Union` or `typing.Optional` needed

## Multi-Version Testing with Tox

We use `tox` to test across all supported Python versions:

```bash
# Test all Python versions
tox

# Test specific Python version
tox -e py310  # Python 3.10
tox -e py311  # Python 3.11
tox -e py312  # Python 3.12
tox -e py313  # Python 3.13

# Run linting only
tox -e lint

# Run formatting only
tox -e format
```

## Modern Development Workflow

### Recommended Approach: Black + Ruff

We've streamlined our development tools to use only **two main tools** instead of the previous four:

```bash
# Format code
black .

# Lint and fix (includes import sorting, style checks, etc.)
ruff check --fix .

# Run tests
pytest
```

### What Ruff Handles

Ruff is a fast Python linter written in Rust that replaces multiple tools:

- **Import sorting** (replaces `isort`)
- **Style checking** (replaces `flake8`)
- **Code quality** (replaces various flake8 plugins)
- **Import organization** (replaces `isort`)
- **Unused imports/variables** (replaces `pyflakes`)

### Complete Workflow

To run all checks and tests:

```bash
black --check .
ruff check .
pytest -q
```

To auto-fix formatting and linting:

```bash
black .
ruff check --fix .
```

## Why This Approach?

### The Problem with Multiple Tools

Previously, we used `isort + black + ruff + flake8`, which caused:

1. **Import sorting conflicts** between `isort` and `ruff`
2. **Endless loops** where each tool "fixed" what the other tool "broke"
3. **Inconsistent results** depending on which tool ran last
4. **Slower CI** with multiple tool executions

### The Solution

**Ruff handles everything** that the other tools did, but:
- **Faster** (written in Rust)
- **Consistent** (single tool, single set of rules)
- **Comprehensive** (covers all our needs)
- **No conflicts** (single source of truth)

## Configuration

### Ruff Configuration

All ruff settings are in `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py310"
line-length = 99

[tool.ruff.lint]
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings  
    "F",      # Pyflakes
    "I",      # isort (import sorting)
    "N",      # pep8-naming
    "D",      # pydocstyle
    # ... and many more
]

[tool.ruff.lint.isort]
combine-as-imports = true
force-sort-within-sections = true
```

### Black Configuration

```toml
[tool.black]
line-length = 99
```

## Migration from Old Workflow

### What Changed

| Old Tool | New Tool | Status |
|----------|----------|---------|
| `isort` | `ruff` with `"I"` rule | ✅ Replaced |
| `flake8` | `ruff` with comprehensive rules | ✅ Replaced |
| `black` | `black` | ✅ Kept |
| `pytest` | `pytest` | ✅ Kept |

### What to Stop Using

- ❌ **Don't run `isort`** - it conflicts with ruff
- ❌ **Don't run `flake8`** - ruff covers everything
- ❌ **Don't run multiple tools** - use ruff for everything

### What to Use Instead

- ✅ **Use `ruff check --fix`** for all linting and import sorting
- ✅ **Use `black`** for code formatting
- ✅ **Use `pytest`** for testing

## Troubleshooting

### Common Issues

**"Import sorting conflicts"**
- **Cause**: Running both `isort` and `ruff`
- **Solution**: Use only `ruff check --fix`

**"Different results each time"**
- **Cause**: Multiple tools with different rules
- **Solution**: Use only `ruff` for linting

**"CI failing inconsistently"**
- **Cause**: Tool order dependencies
- **Solution**: Use streamlined workflow

### Getting Help

1. **Check ruff output**: `ruff check . --verbose`
2. **Review configuration**: Check `pyproject.toml` ruff settings
3. **Run auto-fix**: `ruff check --fix .`
4. **Check specific rules**: `ruff check . --select I` (imports only)

## Best Practices

1. **Always use `ruff check --fix`** before committing
2. **Run `black .`** for consistent formatting
3. **Use `pytest`** for testing
4. **Don't mix old and new tools**
5. **Let ruff handle all linting** (imports, style, quality)

## Benefits

- **Faster development** - single tool for all linting
- **Consistent results** - no more import sorting conflicts
- **Better performance** - Rust-based tooling
- **Simplified CI** - fewer steps, faster builds
- **Modern standards** - follows current Python best practices
