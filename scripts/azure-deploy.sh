#!/usr/bin/env bash
# Deploy the app on the existing infrastructure: build and push the image, then deploy infra/app.bicep (the
# Container App only). The infrastructure comes from scripts/azure-up.sh, once.
#   scripts/azure-deploy.sh
#   ALLOWED_IPS=203.0.113.4/32 scripts/azure-deploy.sh   # only these addresses (ALLOWED_IPS= opens it again)
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/azure-lib.sh
source scripts/azure-lib.sh

need docker
az_login
[ -f "$STATE" ] || { echo "No $STATE: create the infrastructure first with scripts/azure-up.sh" >&2; exit 1; }
load_state
save_state

out() { az deployment group show -g "$RG" -n infra --query "properties.outputs.$1.value" -o tsv; }
ACR_NAME=$(out acrName)
IMAGE="$(out acrLoginServer)/dottie:$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD 2>/dev/null || echo nocommit)"
[ -z "$(git status --porcelain)" ] || echo "Note: uncommitted changes go into this image; its tag names HEAD."

echo "== Image $IMAGE"
docker build --platform linux/amd64 -t "$IMAGE" .
az acr login -n "$ACR_NAME"
docker push "$IMAGE"

echo "== App (app.bicep)"
FQDN=$(az deployment group create -g "$RG" -n app -f infra/app.bicep \
  -p location="${APP_LOCATION:-$LOCATION}" sandboxRegion="$LOCATION" image="$IMAGE" ipRules="$(ip_rules_json)" \
  --query properties.outputs.fqdn.value -o tsv)

echo
echo "Running at https://$FQDN (the first request after an idle period starts it: a few seconds)"
[ -n "${ALLOWED_IPS:-}" ] ||
  echo "No sign-in and no IP rules: anyone with this URL can use the app."
