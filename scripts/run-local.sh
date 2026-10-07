#!/usr/bin/env bash
# Run the app on this machine, settings from .env.
#   scripts/run-local.sh          # build the frontend, serve everything on PORT (8370)
#   scripts/run-local.sh --dev    # Vite with hot reload on http://localhost:5173 (proxies /api to the backend)
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh

dev=""
case "${1:-}" in
  "") ;;
  --dev) dev=1 ;;
  *) echo "usage: $0 [--dev]" >&2; exit 1 ;;
esac

need uv "https://docs.astral.sh/uv/getting-started/installation/"
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example."; }
# the secret store needs a key; make one the first time (changing it later makes stored secrets unreadable)
grep -q '^SECRETS_KEY=.' .env || { sed -i '/^SECRETS_KEY=/d' .env; echo "SECRETS_KEY=$(openssl rand -base64 32)" >> .env; }
uv sync
# fail now, not after the build, when another app holds the port
port=$(uv run python -c "from dottie.config import get_settings; print(get_settings().port)")
if (echo >"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
  holder=$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'users:(([^)]*' | head -1)
  echo "Port $port is in use${holder:+ ($holder)}: stop that, or set PORT in .env." >&2
  exit 1
fi
export PORT="$port"  # for Vite's proxy (--dev)
scripts/db.sh up

need npm "https://nodejs.org"
[ -d frontend/node_modules ] || (cd frontend && npm ci)
if [ -n "$dev" ]; then
  (cd frontend && npm run dev) &
  trap 'kill $! 2>/dev/null || true' EXIT
else
  (cd frontend && npm run build)
fi
uv run dottie
