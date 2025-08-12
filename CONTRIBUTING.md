# Contributing to DiscordianAI

Thank you for your interest in contributing! This project follows modern Python best practices for code quality, testing, and documentation.

## Development Setup

### Prerequisites

- **Python**: 3.10
- **Git**: Latest version
- **pip**: Latest version

### Environment Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/johndotpub/DiscordianAI.git
   cd DiscordianAI
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install development dependencies**:
   ```bash
   pip install -e .[dev]
   ```

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

**Modern Approach (Recommended):**
- **black (check only):**
  ```bash
  black --check .
  ```
- **ruff (check only):**
  ```bash
  ruff check .
  ```

**Legacy Approach (Not Recommended):**
- **flake8:**
  ```bash
  flake8 .
  ```
- **isort (check only):**
  ```bash
  isort --check .
  ```

### Full Workflow

To run all checks and tests:

```bash
black --check .
ruff check .
pytest
```

To auto-fix formatting and linting:

```bash
black .
ruff check --fix .
```

### Continuous Integration

All pushes and pull requests are automatically checked with black, ruff, and pytest via GitHub Actions. Please ensure your code passes all checks before submitting a PR.

## Code Style
- Follow PEP8 and use black for formatting.
- Keep imports sorted with ruff (includes isort functionality).
- Write clear, maintainable, and well-documented code.
- Add or update tests for any new features or bugfixes.

## Questions?
If you have any questions, open an issue or ask in the PR comments. Thank you for helping make DiscordianAI better! 