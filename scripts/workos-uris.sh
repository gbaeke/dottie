#!/usr/bin/env bash
# Add or remove an address of the app in its WorkOS environment: the redirect URI (<url>/auth/callback) and the
# sign-out URI (<url>/). Other URIs and the defaults are kept. Uses the WorkOS CLI (npm install -g workos, then
# workos auth login) and jq.
#   WORKOS_CLIENT_ID=client_... scripts/workos-uris.sh add http://localhost:8370
#   WORKOS_CLIENT_ID=client_... scripts/workos-uris.sh remove https://dottie.<...>.azurecontainerapps.io
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh

usage="usage: WORKOS_CLIENT_ID=client_... $0 add|remove <app url>"
action="${1:?$usage}" url="${2:?$usage}"
url="${url%/}"
case "$action" in add | remove) ;; *) echo "$usage" >&2; exit 1 ;; esac
: "${WORKOS_CLIENT_ID:?$usage}"
need jq
need workos "npm install -g workos"
[ "$(workos auth status --mode agent | jq -r .authenticated)" = "true" ] || {
  echo "The WorkOS CLI is not signed in: run workos auth login" >&2
  exit 1
}
env_id=$(workos project list --mode agent |
  jq -r --arg c "$WORKOS_CLIENT_ID" '.projects[].environments[] | select(.clientId == $c) | .id')
[ -n "$env_id" ] || { echo "No environment with client id $WORKOS_CLIENT_ID in this WorkOS account." >&2; exit 1; }

# update KIND URI: add or remove URI in the list KIND (redirect-uris, logout-uris); `set` replaces the whole list
update() {
  local kind=$1 uri=$2 key current uris default args=()
  key=$([ "$kind" = redirect-uris ] && echo redirectUris || echo logoutUris)
  current=$(workos authkit "$kind" list --environment-id "$env_id" --mode agent)
  if [ "$action" = add ]; then
    uris=$(jq -r --arg k "$key" --arg u "$uri" '[.[$k][].uri] + [$u] | unique | .[]' <<<"$current")
  else
    uris=$(jq -r --arg k "$key" --arg u "$uri" '[.[$k][].uri | select(. != $u)] | .[]' <<<"$current")
  fi
  if [ "$(sort <<<"$uris")" = "$(jq -r --arg k "$key" '.[$k][].uri' <<<"$current" | sort)" ]; then
    echo "  $kind unchanged: $uri"
    return
  fi
  [ -n "$uris" ] || { echo "  $kind: not removing the last URI ($uri); do it in the dashboard" >&2; return; }
  default=$(jq -r --arg k "$key" '.[$k][] | select(.isDefault) | .uri' <<<"$current")
  grep -qxF "$default" <<<"$uris" || default=$(head -n1 <<<"$uris")
  while read -r u; do args+=(--uri "$u"); done <<<"$uris"
  workos authkit "$kind" set --environment-id "$env_id" "${args[@]}" --default "$default" --mode agent >/dev/null
  echo "  $kind: ${action}ed $uri"
}

echo "== WorkOS ($env_id)"
update redirect-uris "$url/auth/callback"
update logout-uris "$url/"
