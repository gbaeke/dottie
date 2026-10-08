# shellcheck shell=bash
# Shared by the azure-*.sh scripts: the resource group, az login, and the deployment's state file.
#
# The state file .azure/<resource group>.env (git-ignored, private) keeps what every deploy needs again: the region,
# ALLOWED_IPS. A variable set in the
# environment wins over the file and is saved for the next run; set it empty to clear it.

# shellcheck source=scripts/lib.sh
source scripts/lib.sh

RG="${AZURE_RESOURCE_GROUP:-rg-dottie}"
STATE=".azure/$RG.env"
STATE_VARS="LOCATION APP_LOCATION ALLOWED_IPS AGENT_MODE WORKOS_CLIENT_ID WORKOS_API_KEY SESSION_SECRET ALLOWED_USERS SECRETS_KEY TELEGRAM_BOT_TOKEN"

# az_login: exit unless az is installed and logged in; prints the subscription
az_login() {
  need az "https://learn.microsoft.com/cli/azure/install-azure-cli"
  local sub
  sub=$(az account show --query "[name, id]" -o tsv 2>/dev/null | paste -sd ' ') || {
    echo "Not logged in: run az login" >&2
    exit 1
  }
  echo "Subscription: $sub"
  echo "Resource group: $RG"
}

# load_state: the state file's values, overridden by any of STATE_VARS set in the environment
load_state() {
  local given="" v
  for v in $STATE_VARS; do
    [ -z "${!v+x}" ] || given="$given$(printf '%s=%q; ' "$v" "${!v}")"
  done
  # shellcheck disable=SC1090
  [ -f "$STATE" ] && source "$STATE"
  eval "$given"
}

save_state() {
  mkdir -p .azure
  (
    umask 077
    for v in $STATE_VARS; do printf '%s=%q\n' "$v" "${!v:-}"; done >"$STATE"
  )
}

# ip_rules_json: ALLOWED_IPS (comma separated CIDRs) as Container Apps ingress rules; [] is open to everyone
ip_rules_json() {
  local json="" i=0 cidr
  IFS=',' read -ra cidrs <<<"${ALLOWED_IPS:-}"
  for cidr in ${cidrs[@]+"${cidrs[@]}"}; do
    i=$((i + 1))
    json="$json${json:+,}{\"name\":\"allow-$i\",\"action\":\"Allow\",\"ipAddressRange\":\"$cidr\"}"
  done
  echo "[$json]"
}
