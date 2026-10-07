#!/usr/bin/env bash
# What is behind: packages, runtimes and pinned versions in this repo. Reports only; upgrading is a separate,
# deliberate change (a major version on its own branch, after reading its changelog).
#   scripts/versions.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

step() { printf '\n== %s\n' "$1"; }

step "Python packages (direct dependencies with a newer release)"
uv tree --outdated --depth 1 2>/dev/null | grep -E 'latest: ' || echo "all current"

step "npm packages"
(cd frontend && npm outdated) && echo "all current"

# latest_cycle PRODUCT [lts]: the newest release line on endoflife.date (python, nodejs, postgresql); with lts, the
# newest line whose LTS has started
latest_cycle() {
  curl -fsS "https://endoflife.date/api/$1.json" 2>/dev/null | python3 -c '
import datetime, json, sys
lts = len(sys.argv) > 1
today = datetime.date.today().isoformat()
for c in json.load(sys.stdin):
    if not lts or (isinstance(c.get("lts"), str) and c["lts"] <= today):
        print(c["cycle"])
        break' ${2:+lts} 2>/dev/null || echo "?"
}

step "Runtimes (pinned here vs newest release line)"
printf '%-12s %-28s %s\n' "python" "$(cat .python-version), Dockerfile" "$(latest_cycle python)"
printf '%-12s %-28s %s\n' "node" "$(grep -o 'node:[0-9]*' Dockerfile | head -1)" "$(latest_cycle nodejs lts) (newest LTS)"
printf '%-12s %-28s %s\n' "postgresql" "$(grep -o 'postgres:[0-9]*' compose.yaml | head -1)" "$(latest_cycle postgresql) (keep compose.yaml, CI and infra/main.bicep on one major)"

step "GitHub Actions"
grep -ho 'uses: [^ ]*' .github/workflows/*.yml | sort -u | while read -r _ action; do
  repo=${action%@*} pinned=${action#*@}
  latest=$(gh api "repos/$repo/releases/latest" --jq .tag_name 2>/dev/null || echo "?")
  [ "${latest%%.*}" = "$pinned" ] || printf '%-28s %-6s -> %s\n' "$repo" "$pinned" "$latest"
done

step "Bicep API versions (linter rule use-recent-api-versions)"
if command -v az >/dev/null; then
  az bicep lint --file infra/main.bicep 2>&1 | grep -i 'use-recent-api-versions' || echo "all current"
else
  echo "skipped: az is not installed"
fi
