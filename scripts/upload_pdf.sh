#!/usr/bin/env bash
# Upload one or more PDFs to invoices-in (triggers both OCR functions).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/terraform"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <file.pdf> [more.pdf ...]"
  exit 1
fi

STORAGE="$(terraform -chdir="$TF_DIR" output -raw storage_account_name)"
RG="$(terraform -chdir="$TF_DIR" output -raw resource_group_name)"

# Ensure current user can write blobs via AAD
SCOPE="$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)"
ASSIGNEE="$(az ad signed-in-user show --query id -o tsv)"
az role assignment create --assignee "$ASSIGNEE" --role "Storage Blob Data Contributor" --scope "$SCOPE" 2>/dev/null || true

# RBAC can take a minute to propagate on first run
for f in "$@"; do
  name="$(basename "$f")"
  echo "Uploading $f → invoices-in/$name"
  az storage blob upload \
    --account-name "$STORAGE" \
    --container-name invoices-in \
    --file "$f" \
    --name "$name" \
    --auth-mode login \
    --overwrite true
done

echo "Done. JSON will appear in invoices-out-read/ and invoices-out-invoice/ within ~1–2 min."
