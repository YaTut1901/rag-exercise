#!/usr/bin/env bash
# Zip-deploy Streamlit UI with preinstalled deps (no Oryx — B1 OOMs on remote pip).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/_common.sh
source "$ROOT/scripts/_common.sh"
TF_DIR="$ROOT/terraform"
UI_DIR="$ROOT/agent"
BUILD_DIR="$ROOT/.build/ui_pkg"
ZIP_PATH="$ROOT/.build/ui.zip"

UI_APP_NAME="${1:-}"
RESOURCE_GROUP="${2:-}"

if [[ -z "$UI_APP_NAME" || -z "$RESOURCE_GROUP" ]]; then
  UI_APP_NAME="$(terraform -chdir="$TF_DIR" output -raw ui_app_name)"
  RESOURCE_GROUP="$(terraform -chdir="$TF_DIR" output -raw resource_group_name)"
fi

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  if command -v python3.11 >/dev/null 2>&1; then
    PY=python3.11
  else
    PY=python3
  fi
fi

mkdir -p "$ROOT/.build"
rm -rf "$BUILD_DIR" "$ZIP_PATH"
mkdir -p "$BUILD_DIR"

echo "Packaging UI with $PY (preinstall into .python_packages)…"
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' "$UI_DIR/" "$BUILD_DIR/"
"$PY" -m pip install -q -r "$UI_DIR/requirements.txt" -t "$BUILD_DIR/.python_packages/lib/site-packages"
(
  cd "$BUILD_DIR"
  zip -qr "$ZIP_PATH" .
)

echo "Deploying $ZIP_PATH → $UI_APP_NAME ($RESOURCE_GROUP) [no remote build]"
az webapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$UI_APP_NAME" \
  --settings \
    SCM_DO_BUILD_DURING_DEPLOYMENT=false \
    ENABLE_ORYX_BUILD=false \
    PYTHONPATH=/home/site/wwwroot/.python_packages/lib/site-packages \
  -o none

az webapp deploy \
  --resource-group "$RESOURCE_GROUP" \
  --name "$UI_APP_NAME" \
  --src-path "$ZIP_PATH" \
  --type zip \
  --async false

echo "UI: $(terraform -chdir="$TF_DIR" output -raw ui_url)"
