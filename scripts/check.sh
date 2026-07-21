#!/usr/bin/env bash
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -x .venv/bin/python ]]; then
    PATH="$(pwd)/.venv/bin:$PATH"
fi

echo "==> black --check"
black --check .

echo "==> ruff check"
ruff check .

echo "==> mypy src/"
mypy src/

echo "==> mypy tests/"
mypy tests/

echo "==> guard: no print() in src/"
if grep -rn "print(" src/ 2>/dev/null; then
    echo "FAIL: print() found in src/ — use logging instead"
    exit 1
fi

echo "==> guard: no bare except:"
if grep -rn "except:" src/ tests/ 2>/dev/null; then
    echo "FAIL: bare except: found — catch a specific exception"
    exit 1
fi

echo "==> TODO/FIXME scan (warning only)"
grep -rn "TODO\|FIXME" src/ tests/ 2>/dev/null || true

echo "==> pytest --cov"
pytest --cov --cov-fail-under=70

echo "==> all checks passed"
