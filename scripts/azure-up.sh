#!/usr/bin/env bash
# Create or update the shared infrastructure (infra/main.bicep), then deploy the app (scripts/azure-deploy.sh).
# Run it the first time and when main.bicep changes; for a new version of the app, azure-deploy.sh is enough.
#   scripts/azure-up.sh                              # resource group rg-dottie in swedencentral
#   AZURE_RESOURCE_GROUP=rg-x LOCATION=westeurope scripts/azure-up.sh
#   YES=1 scripts/azure-up.sh                        # do not ask for confirmation
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/azure-lib.sh
source scripts/azure-lib.sh

az_login
load_state
LOCATION="${LOCATION:-swedencentral}"
APP_LOCATION="${APP_LOCATION:-$LOCATION}"  # the app and its environment may live elsewhere (capacity)
echo "Region: $LOCATION (app: $APP_LOCATION)"
confirm "Create or update the infrastructure here? This creates billable resources."
save_state

echo "== Infrastructure (main.bicep)"
az group create -n "$RG" -l "$LOCATION" -o none
# you become a PostgreSQL admin next to the app's identity (psql with an az login token: see the README)
read -r ADMIN_ID ADMIN_NAME < <(az ad signed-in-user show --query "[id, userPrincipalName]" -o tsv | paste -sd ' ')
az deployment group create -g "$RG" -n infra -f infra/main.bicep \
  -p location="$LOCATION" appLocation="$APP_LOCATION" adminObjectId="$ADMIN_ID" adminName="$ADMIN_NAME" -o none

# The sandbox group (the dotties' computers) is created here and not in main.bicep: ARM's preflight validation for
# Microsoft.App/sandboxGroups rejects every template (preview resource type), while a direct PUT works.
echo "== Sandbox group"
out() { az deployment group show -g "$RG" -n infra --query "properties.outputs.$1.value" -o tsv; }
SUB=$(az account show --query id -o tsv)
GROUP="sbg-$(out suffix)"
GROUP_ID="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/sandboxGroups/$GROUP"
az rest --method put --url "https://management.azure.com$GROUP_ID?api-version=2026-07-01" \
  --body "{\"location\":\"$LOCATION\"}" -o none
until [ "$(az rest --method get --url "https://management.azure.com$GROUP_ID?api-version=2026-07-01" \
  --query properties.provisioningState -o tsv)" = "Succeeded" ]; do sleep 5; done
# the app's identity and you may create and drive sandboxes ("Container Apps SandboxGroup Data Owner")
OWNER=c24cf47c-5077-412d-a19c-45202126392c
az role assignment create --role "$OWNER" --scope "$GROUP_ID" --assignee-object-id "$(out identityPrincipalId)" \
  --assignee-principal-type ServicePrincipal -o none 2>/dev/null || true
az role assignment create --role "$OWNER" --scope "$GROUP_ID" --assignee-object-id "$ADMIN_ID" \
  --assignee-principal-type User -o none 2>/dev/null || true

YES=1 scripts/azure-deploy.sh
