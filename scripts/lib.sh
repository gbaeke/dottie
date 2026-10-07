# shellcheck shell=bash
# Helpers for the scripts in this folder (bash 3.2 and later), sourced from the repository root.

# need TOOL [WHERE TO GET IT]: exit unless TOOL is installed
need() {
  command -v "$1" >/dev/null || {
    echo "$1 is not installed${2:+: $2}" >&2
    exit 1
  }
}

# confirm QUESTION: exit unless the answer is y (YES=1 answers for you)
confirm() {
  [ -z "${YES:-}" ] || return 0
  local answer
  read -r -p "$1 [y/N] " answer
  [ "$answer" = "y" ] || [ "$answer" = "Y" ] || exit 1
}

# wait_for TRIES SECONDS WHAT COMMAND...: run COMMAND every SECONDS until it succeeds; exit after TRIES failures
wait_for() {
  local tries=$1 interval=$2 what=$3 i
  shift 3
  for ((i = 1; i <= tries; i++)); do
    "$@" && return 0
    sleep "$interval"
  done
  echo "$what is still not ready after $tries tries" >&2
  exit 1
}
