# Python Version Compatibility

DiscordianAI is designed to work with Python 3.10 only, providing a simple and straightforward development experience.

## Supported Python Versions

| Version | Status | Notes |
|---------|--------|-------|
| **Python 3.10** | ✅ **Fully Supported** | Only supported version |

## Version Requirements

- **Required**: Python 3.10.x
- **No other versions supported**

## Modern Python Features Used

DiscordianAI leverages modern Python features that are available in Python 3.10:

### Type Annotations (Python 3.9+)
```python
# Generic type annotations
def process_messages(messages: list[dict[str, str]]) -> dict[str, Any]:
    pass

# Built-in collection types
from typing import Dict, List  # No longer needed!
```

### Union Types (Python 3.10+)
```python
# Modern union syntax
def get_user_data(user_id: int | None) -> dict[str, Any] | None:
    pass

# Instead of typing.Union[int, None]
```

### Pattern Matching (Python 3.10+)
```python
# Available but not currently used in codebase
match status:
    case "healthy":
        return "Service is running"
    case "degraded":
        return "Service has issues"
    case _:
        return "Unknown status"
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

We use `tox` to ensure compatibility with Python 3.10:

```bash
# Test Python 3.10
tox -e py310

# Run linting
tox -e lint

# Run formatting
tox -e format
```

## CI/CD Testing

Our GitHub Actions workflow automatically tests:
- **Python version** (3.10 only)
- **Linting and formatting** with black + ruff
- **Unit tests** with pytest
- **Full tox suite** for comprehensive validation

## Dependency Compatibility

All project dependencies are verified to work with Python 3.10:

- **discord.py**: ✅ Python 3.8+
- **openai**: ✅ Python 3.7+
- **websockets**: ✅ Python 3.7+
- **pytest**: ✅ Python 3.7+
- **ruff**: ✅ Python 3.8+
- **black**: ✅ Python 3.7+

## Migration Guide

### From Python 3.9 or Earlier

If you're upgrading from Python 3.9 or earlier, you may need to:

1. **Update type annotations**:
   ```python
   # Old (Python 3.8-3.9)
   from typing import List, Dict, Union
   def func(data: List[Dict[str, Union[str, int]]]) -> None:
       pass
   
   # New (Python 3.10+)
   def func(data: list[dict[str, str | int]]) -> None:
       pass
   ```

2. **Remove typing imports**:
   ```python
   # No longer needed
   from typing import Optional, Union, List, Dict
   ```

3. **Update pip and setuptools**:
   ```bash
   pip install --upgrade pip setuptools wheel
   ```

### From Python 3.10+

No changes required! Your code will work as-is.

## Performance Considerations

- **Python 3.10**: Stable, well-tested, recommended for production

## Troubleshooting

### Common Issues

1. **ImportError: cannot import name 'X' from 'typing'**
   - Solution: Use built-in types instead of typing imports
   - Example: `list[str]` instead of `List[str]`

2. **SyntaxError: invalid syntax**
   - Check Python version: `python --version`
   - Ensure you're using Python 3.10.x

3. **tox environment creation fails**
   - Install Python 3.10.x interpreter
   - Use `tox --skip-missing-interpreters` if needed

### Getting Help

- Check your Python version: `python --version`
- Verify tox installation: `tox --version`
- Run tests with verbose output: `tox -v`
- Check CI logs for specific version failures

## Future Compatibility

We're committed to:
- **Maintaining Python 3.10 support** for the foreseeable future
- **Simple and straightforward** version management
- **Stable development environment** with minimal compatibility concerns
