#!/usr/bin/env bash
# Run every repository gate in order and stop at the first failure.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -n "${PYTHON:-}" ]]; then
    PYTHON_BIN="$PYTHON"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

echo "==> black"
"$PYTHON_BIN" -m black . --check --diff

echo "==> ruff"
"$PYTHON_BIN" -m ruff check .

echo "==> pytest"
"$PYTHON_BIN" -m pytest

echo "==> sphinx (warnings as errors)"
"$PYTHON_BIN" -m sphinx -b html docs/api docs/api/_build -W

echo "==> wheel build"
WHEEL_DIR="$(mktemp -d)"
trap 'rm -rf "$WHEEL_DIR"' EXIT
if "$PYTHON_BIN" -c "import importlib.metadata as m; m.version('build')" >/dev/null 2>&1; then
    "$PYTHON_BIN" -m build --wheel --outdir "$WHEEL_DIR"
else
    "$PYTHON_BIN" -m pip wheel . --no-deps --wheel-dir "$WHEEL_DIR"
fi
ls -l "$WHEEL_DIR"/*.whl

echo "All preflight gates passed."
