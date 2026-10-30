#!/usr/bin/env bash
# Upload one or more PDFs to invoices-in (Event Grid → q-ingress).
# Requires AAD login so uploaderEmail metadata can be set for notifications.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/_common.sh
source "$ROOT/scripts/_common.sh"
TF_DIR="$ROOT/terraform"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <file.pdf> [more.pdf ...]"
  exit 1
fi

STORAGE="$(terraform -chdir="$TF_DIR" output -raw storage_account_name)"
RG="$(terraform -chdir="$TF_DIR" output -raw resource_group_name)"

SCOPE="$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)"
ASSIGNEE="$(az ad signed-in-user show --query id -o tsv)"
az role assignment create --assignee "$ASSIGNEE" --role "Storage Blob Data Contributor" --scope "$SCOPE" 2>/dev/null || true
wait_blob_data_rbac "$STORAGE" "invoices-in"

UPLOADER_EMAIL="$(az ad signed-in-user show --query 'mail' -o tsv 2>/dev/null || true)"
if [[ -z "${UPLOADER_EMAIL}" || "${UPLOADER_EMAIL}" == "null" ]]; then
  UPLOADER_EMAIL="$(az ad signed-in-user show --query 'userPrincipalName' -o tsv)"
fi
echo "uploaderEmail=$UPLOADER_EMAIL"

for f in "$@"; do
  name="$(basename "$f")"
  echo "Uploading $f → invoices-in/$name"
  az storage blob upload \
    --account-name "$STORAGE" \
    --container-name invoices-in \
    --file "$f" \
    --name "$name" \
    --auth-mode login \
    --overwrite true \
    --metadata "uploaderEmail=${UPLOADER_EMAIL}"
done

echo "Done. Pipeline: Event Grid → q-ingress → classify → extract → notify/delete."
