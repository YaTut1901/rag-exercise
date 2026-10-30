# shellcheck shell=bash
# Shared helpers for lab scripts (source from other scripts).

# Wait until AAD Storage Blob Data RBAC is usable for --auth-mode login.
# Azure role assignments often take 30–90s to propagate.
wait_blob_data_rbac() {
  local account="$1"
  local container="$2"
  local attempts="${3:-18}"
  local delay_sec="${4:-5}"
  local i=1

  echo "Waiting for Blob Data RBAC on ${account}/${container} (up to $((attempts * delay_sec))s)..."
  while (( i <= attempts )); do
    if az storage container show \
      --account-name "$account" \
      --name "$container" \
      --auth-mode login \
      -o none 2>/dev/null; then
      echo "Blob Data RBAC ready (${i}/${attempts})."
      return 0
    fi
    echo "  not ready, sleep ${delay_sec}s (${i}/${attempts})"
    sleep "$delay_sec"
    i=$((i + 1))
  done
  echo "ERROR: Blob Data RBAC not ready for ${account}/${container}" >&2
  return 1
}

# Brief settle after Function App restart / appsettings change.
wait_function_app_settle() {
  local seconds="${1:-30}"
  echo "Waiting ${seconds}s for Function App to settle..."
  sleep "$seconds"
}
