#!/usr/bin/env bash
# fetch-bearer.sh — populate /run/cktest-runner/env with CKTEST_RUNNER_BEARER
# fetched live from the hadoku_site vault broker.
#
# Run as systemd ExecStartPre. Fails closed: if the vault is sealed, the
# service key is missing/rejected, or the broker is unreachable, this
# script exits non-zero and systemd refuses to start the unit. That's
# the desired behavior — a vault outage should surface as a service
# outage, not a service running with a stale or empty bearer.
#
# Pattern matches the per-(actor × wrapper) ACL design from
# hadoku_site/docs/planning/vault-per-key-acl.md: this host's service key
# is ACL-scoped on the broker side to just CKTEST_RUNNER_BEARER, so a
# leaked key only exposes that one secret.

set -euo pipefail

SERVICE_KEY_PATH="${CKTEST_SERVICE_KEY_PATH:-/etc/cktest-runner/service.key}"
BROKER_URL="${CKTEST_VAULT_BROKER_URL:-https://hadoku.me/mgmt/api/secrets/get/CKTEST_RUNNER_BEARER}"
ENV_OUT="${CKTEST_ENV_OUT:-/run/cktest-runner/env}"

# ── Pre-flight checks. Each gives an actionable journald line.
if [[ ! -r "${SERVICE_KEY_PATH}" ]]; then
  echo "fetch-bearer: service key not readable at ${SERVICE_KEY_PATH}" >&2
  echo "  remediation: operator runs \`administration.py key-generate" >&2
  echo "    --tier service --name claws-cktest-fetcher\` and copies the" >&2
  echo "    UUID to ${SERVICE_KEY_PATH} (mode 0600, owner cktest:cktest)" >&2
  exit 1
fi

SERVICE_KEY="$(tr -d '[:space:]' < "${SERVICE_KEY_PATH}")"
if [[ -z "${SERVICE_KEY}" ]]; then
  echo "fetch-bearer: service key file is empty (${SERVICE_KEY_PATH})" >&2
  exit 1
fi

# Ensure the runtime dir exists with the right perms (systemd's
# RuntimeDirectory= already does this, but defensive in case the script
# is invoked outside the unit for debugging).
mkdir -p "$(dirname "${ENV_OUT}")"
chmod 0750 "$(dirname "${ENV_OUT}")"

# ── Fetch. Capture status separately so we can give a precise diagnosis
#    rather than just "curl failed".
TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

HTTP_STATUS="$(curl --silent --show-error --fail-with-body \
  --max-time 10 \
  --header "X-User-Key: ${SERVICE_KEY}" \
  --output "${TMP}" \
  --write-out '%{http_code}' \
  "${BROKER_URL}" || true)"

case "${HTTP_STATUS}" in
  200)
    : # ok
    ;;
  401|403)
    echo "fetch-bearer: vault rejected service key (${HTTP_STATUS})" >&2
    echo "  remediation: confirm the key is registered + ACL-granted to" >&2
    echo "    CKTEST_RUNNER_BEARER. See hadoku_site \`administration.py" >&2
    echo "    key-acl-sync\`." >&2
    exit 1
    ;;
  423|503)
    echo "fetch-bearer: vault is sealed or broker unavailable (${HTTP_STATUS})" >&2
    echo "  remediation: operator unlocks the vault on the main host." >&2
    exit 1
    ;;
  000)
    echo "fetch-bearer: could not reach ${BROKER_URL} (network/DNS)" >&2
    exit 1
    ;;
  *)
    echo "fetch-bearer: unexpected status ${HTTP_STATUS} from ${BROKER_URL}" >&2
    cat "${TMP}" >&2 || true
    exit 1
    ;;
esac

# Vault returns the raw secret value as the response body. Strip any
# trailing newline so the env file doesn't end up with a literal `\n` in
# the bearer.
BEARER="$(tr -d '\r\n' < "${TMP}")"
if [[ -z "${BEARER}" ]]; then
  echo "fetch-bearer: vault returned 200 but with empty body" >&2
  exit 1
fi

# Write the env file atomically (rename is atomic on the same fs).
ENV_TMP="${ENV_OUT}.tmp"
{
  echo "CKTEST_RUNNER_BEARER=${BEARER}"
} > "${ENV_TMP}"
chmod 0640 "${ENV_TMP}"
mv -f "${ENV_TMP}" "${ENV_OUT}"

echo "fetch-bearer: wrote ${ENV_OUT} (bearer length=${#BEARER})"
