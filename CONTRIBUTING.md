# Contributing to DiscordianAI

Thank you for your interest in contributing! This project follows modern Python best practices for code quality, testing, and documentation.

## Development & Testing

### Install Dev Dependencies

```bash
pip install -e .[dev]
```

### Run Tests

```bash
pytest
```

### Linting & Formatting

- **flake8:**
  ```bash
  flake8 .
  ```
- **black (check only):**
  ```bash
  black --check .
  ```
- **isort (check only):**
  ```bash
  isort --check .
  ```
- **autopep8 (auto-fix):**
  ```bash
  autopep8 -r . --in-place
  ```

### Full Workflow

To run all checks and tests:

```bash
flake8 .
black --check .
isort --check .
pytest
```

To auto-fix formatting:

```bash
black .
isort .
autopep8 -r . --in-place
```

### Continuous Integration

All pushes and pull requests are automatically checked with flake8 and pytest via GitHub Actions. Please ensure your code passes all checks before submitting a PR.

## Code Style
- Follow PEP8 and use black for formatting.
- Keep imports sorted with isort.
- Write clear, maintainable, and well-documented code.
- Add or update tests for any new features or bugfixes.

## Questions?
If you have any questions, open an issue or ask in the PR comments. Thank you for helping make DiscordianAI better! 