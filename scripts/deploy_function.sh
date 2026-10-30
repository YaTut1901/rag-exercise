#!/usr/bin/env bash
# Zip-deploy Azure Functions code to the Function App created by Terraform.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/terraform"
FUNC_DIR="$ROOT/function"
ZIP_PATH="$ROOT/.build/function.zip"

FUNCTION_APP_NAME="${1:-}"
RESOURCE_GROUP="${2:-}"

if [[ -z "$FUNCTION_APP_NAME" || -z "$RESOURCE_GROUP" ]]; then
  FUNCTION_APP_NAME="$(terraform -chdir="$TF_DIR" output -raw function_app_name)"
  RESOURCE_GROUP="$(terraform -chdir="$TF_DIR" output -raw resource_group_name)"
fi

mkdir -p "$ROOT/.build"
rm -f "$ZIP_PATH"

# Azure remote build resolves requirements.txt on the server
(
  cd "$FUNC_DIR"
  zip -r "$ZIP_PATH" . \
    -x '*/__pycache__/*' \
    -x '*.pyc' \
    -x '.venv/*' \
    -x 'local.settings.json' \
    -x '.python_packages/*'
)

echo "Deploying $ZIP_PATH → $FUNCTION_APP_NAME ($RESOURCE_GROUP)"
az functionapp deployment source config-zip \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --src "$ZIP_PATH" \
  --build-remote true

echo "Waiting for app to settle..."
sleep 15
az functionapp function list --name "$FUNCTION_APP_NAME" --resource-group "$RESOURCE_GROUP" -o table
