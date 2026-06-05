# Python Version Compatibility

DiscordianAI targets **Python 3.12 and newer**.

## Supported Python Versions

| Version | Status | Notes |
|---------|--------|-------|
| **Python 3.12** | ✅ **Required** | Minimum supported version |
| **Python 3.13+** | ✅ **Compatible** | Should work; CI may add informational tests |

## Version Requirements

- **Required**: Python >= 3.12
- **Not supported**: Python 3.10, 3.11

## Modern Python Features Used

DiscordianAI leverages modern Python features available in Python 3.12:

### Type Annotations (Python 3.9+)
```python
# Generic type annotations
def process_messages(messages: list[dict[str, str]]) -> dict[str, Any]:
    pass

# Built-in collection types
# from typing import Dict, List  # No longer needed!
```

### Union Types (Python 3.10+)
```python
# Modern union syntax
def get_user_data(user_id: int | None) -> dict[str, Any] | None:
    pass
```

### F-String Debugging (Python 3.12)
```python
# Cleaner debug f-strings
print(f"{user_id=}")
```

### Dataclasses (Python 3.7+)
```python
from dataclasses import dataclass

@dataclass
class HealthCheckResult:
    service: str
    status: str
    response_time_ms: float
```

## Testing

We use `tox` to run the canonical CI/test suite:

```bash
# Primary suite (required)
tox -e py312
```

## CI/CD Testing

Our GitHub Actions workflow automatically tests:
- **Python version** (3.12 required)
- **Linting and formatting** with black + ruff
- **Unit tests** with pytest
- **Full tox suite** for comprehensive validation

## Dependency Compatibility

All project dependencies are verified to work with Python 3.12:

- **discord.py**: ✅ Python 3.8+
- **openai**: ✅ Python 3.7+
- **websockets**: ✅ Python 3.7+
- **pytest**: ✅ Python 3.8+
- **ruff**: ✅ Python 3.7+
- **black**: ✅ Python 3.7+

## Launcher Notes

- The launcher resolves Python through pyenv first when pyenv is installed.
- Cron environments must have pyenv initialized and available on PATH so the launcher can find the intended interpreter.

## Migration Guide

### From Python 3.10 or 3.11

If you're upgrading from an older Python version:

1. **Install Python 3.12**:
   ```bash
   # Ubuntu/Debian
   sudo apt update && sudo apt install python3.12 python3.12-venv python3.12-dev

   # macOS (via Homebrew)
   brew install python@3.12
   ```

2. **Create a new virtual environment**:
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate
   ```

3. **Reinstall dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Run the test suite** to confirm compatibility:
   ```bash
   tox -e py312
   ```

## Performance Considerations

- **Python 3.12**: Improved f-string performance, better error messages, and async optimizations

## Troubleshooting

### Common Issues

1. **ImportError: cannot import name 'X' from 'typing'**
   - Solution: Use built-in types instead of typing imports
   - Example: `list[str]` instead of `List[str]`

2. **SyntaxError: invalid syntax**
   - Check Python version: `python --version`
   - Ensure you're using Python 3.12+

3. **tox environment creation fails**
   - Install Python 3.12.x interpreter
   - Use `tox --skip-missing-interpreters` if needed

### Getting Help

- Check your Python version: `python --version`
- Verify tox installation: `tox --version`
- Run tests with verbose output: `tox -v`
- Check CI logs for specific version failures

## Future Compatibility

We're committed to:
- **Staying current with Python releases** as stable versions become available
- **Simple and straightforward** version management
- **Stable development environment** with modern Python features
