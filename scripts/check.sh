#!/usr/bin/env bash
# The quality gate: everything CI runs, in the same order. Green here means green in CI.
#   scripts/check.sh          # check only
#   scripts/check.sh --fix    # first let ruff fix and format what it can
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$1"; }

if [ "${1:-}" = "--fix" ]; then
  uv run ruff check --fix .
  uv run ruff format .
  (cd frontend && npm run --silent format)
fi

step "ruff"
uv run ruff format --check .
uv run ruff check .

step "pyright (types)"
uv run pyright

step "pytest"
uv run pytest

step "frontend: API client up to date with the backend"
before=$(mktemp -d)
cp -r frontend/src/client "$before/"
(cd frontend && npm run --silent gen:api >/dev/null)
diff -rq "$before/client" frontend/src/client >/dev/null || {
  echo "frontend/src/client was stale (the API changed): it is regenerated now, include it in the change." >&2
  exit 1
}
rm -rf "$before"

step "frontend: prettier, oxlint and build (type check)"
(cd frontend && npm run --silent format:check && npm run --silent lint && npm run --silent build)

step "bicep"
if command -v az >/dev/null; then
  for f in infra/*.bicep; do az bicep build --file "$f" --stdout >/dev/null; done
else
  echo "skipped: az is not installed"
fi

step "shellcheck"
if command -v shellcheck >/dev/null; then
  shellcheck -x scripts/*.sh .claude/hooks/*.sh
else
  echo "skipped: shellcheck is not installed"
fi

printf '\nAll checks passed.\n'
