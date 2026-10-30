#!/usr/bin/env bash
# Upload samples/examples/{invoice,other}, generate layout .ocr.json, build DI classifier.
# Native Terraform cannot train classifiers — this script calls the DI admin API.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/_common.sh
source "$ROOT/scripts/_common.sh"
TF_DIR="$ROOT/terraform"
SAMPLES_DIR="${1:-$ROOT/samples/examples}"
CLASSIFIER_ID="${CLASSIFIER_ID:-rag-invoice-classifier}"
PYTHON="${PYTHON:-/home/ivan/miniconda3/bin/python}"
if ! "$PYTHON" -c "import azure.ai.documentintelligence, azure.storage.blob" 2>/dev/null; then
  PYTHON="$(command -v python3)"
fi

STORAGE="$(terraform -chdir="$TF_DIR" output -raw storage_account_name)"
RG="$(terraform -chdir="$TF_DIR" output -raw resource_group_name)"
FUNC="$(terraform -chdir="$TF_DIR" output -raw function_app_name)"
DI_ENDPOINT="$(terraform -chdir="$TF_DIR" output -raw document_intelligence_endpoint)"
DI_NAME="$(terraform -chdir="$TF_DIR" output -raw document_intelligence_name)"
TRAIN_CONTAINER="$(terraform -chdir="$TF_DIR" output -raw classifier_train_container)"
DI_KEY="$(az cognitiveservices account keys list -g "$RG" -n "$DI_NAME" --query key1 -o tsv)"

for cls in invoice other; do
  dir="$SAMPLES_DIR/$cls"
  [[ -d "$dir" ]] || { echo "Missing $dir"; exit 1; }
  count="$(find "$dir" -maxdepth 1 -type f -iname '*.pdf' | wc -l)"
  [[ "$count" -ge 5 ]] || { echo "Class '$cls' has $count PDFs; need ≥5"; exit 1; }
done

SCOPE="$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)"
ASSIGNEE="$(az ad signed-in-user show --query id -o tsv)"
az role assignment create --assignee "$ASSIGNEE" --role "Storage Blob Data Contributor" --scope "$SCOPE" 2>/dev/null || true
wait_blob_data_rbac "$STORAGE" "$TRAIN_CONTAINER"

echo "Uploading PDFs → $STORAGE/$TRAIN_CONTAINER/"
for cls in invoice other; do
  for f in "$SAMPLES_DIR/$cls"/*.pdf; do
    az storage blob upload \
      --account-name "$STORAGE" --container-name "$TRAIN_CONTAINER" \
      --file "$f" --name "${cls}/$(basename "$f")" \
      --auth-mode login --overwrite true -o none
  done
done

export DI_ENDPOINT DI_KEY STORAGE TRAIN_CONTAINER CLASSIFIER_ID
echo "Generating layout .ocr.json + class jsonl, then building classifier..."
"$PYTHON" << 'PY'
import json, os
from datetime import datetime, timezone
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.ai.documentintelligence import (
    DocumentIntelligenceAdministrationClient,
    DocumentIntelligenceClient,
)
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    AzureBlobFileListContentSource,
    BuildDocumentClassifierRequest,
    ClassifierDocumentTypeDetails,
    DocumentContentFormat,
)

endpoint = os.environ["DI_ENDPOINT"].rstrip("/")
key = AzureKeyCredential(os.environ["DI_KEY"])
di = DocumentIntelligenceClient(endpoint, key)
admin = DocumentIntelligenceAdministrationClient(endpoint, key)
container = BlobServiceClient(
    f"https://{os.environ['STORAGE']}.blob.core.windows.net",
    credential=DefaultAzureCredential(),
).get_container_client(os.environ["TRAIN_CONTAINER"])

for b in list(container.list_blobs()):
    if b.name.endswith(".ocr.json") or b.name.endswith(".jsonl"):
        container.delete_blob(b.name)

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
filelists: dict[str, list] = {"invoice": [], "other": []}
for b in container.list_blobs():
    if not b.name.lower().endswith(".pdf"):
        continue
    cls = b.name.split("/", 1)[0]
    print("layout", b.name, flush=True)
    pdf = container.download_blob(b.name).readall()
    result = (
        di.begin_analyze_document(
            "prebuilt-layout",
            AnalyzeDocumentRequest(bytes_source=pdf),
            output_content_format=DocumentContentFormat.TEXT,
        )
        .result()
        .as_dict()
    )
    wrapped = {
        "status": "succeeded",
        "createdDateTime": now,
        "lastUpdatedDateTime": now,
        "analyzeResult": result,
    }
    container.upload_blob(
        b.name + ".ocr.json",
        json.dumps(wrapped).encode("utf-8"),
        overwrite=True,
    )
    filelists[cls].append({"file": b.name})

for cls, rows in filelists.items():
    body = "\n".join(json.dumps(r) for r in rows) + "\n"
    container.upload_blob(f"{cls}.jsonl", body.encode("utf-8"), overwrite=True)
    print(f"{cls}.jsonl → {len(rows)} files", flush=True)
print("OCR + jsonl ready", flush=True)
PY

EXPIRY="$(date -u -d '+2 hours' +%Y-%m-%dT%H:%MZ 2>/dev/null || date -u -v+2H +%Y-%m-%dT%H:%MZ)"
SAS="$(az storage container generate-sas \
  --account-name "$STORAGE" --name "$TRAIN_CONTAINER" \
  --permissions rl --expiry "$EXPIRY" --auth-mode login --as-user -o tsv)"
export CONTAINER_URL="https://${STORAGE}.blob.core.windows.net/${TRAIN_CONTAINER}?${SAS}"

"$PYTHON" << 'PY'
import os
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceAdministrationClient
from azure.ai.documentintelligence.models import (
    AzureBlobFileListContentSource,
    BuildDocumentClassifierRequest,
    ClassifierDocumentTypeDetails,
)

admin = DocumentIntelligenceAdministrationClient(
    os.environ["DI_ENDPOINT"].rstrip("/"),
    AzureKeyCredential(os.environ["DI_KEY"]),
)
url = os.environ["CONTAINER_URL"]
cid = os.environ["CLASSIFIER_ID"]
details = admin.begin_build_classifier(
    BuildDocumentClassifierRequest(
        classifier_id=cid,
        description="invoice vs other (lab-2)",
        doc_types={
            "invoice": ClassifierDocumentTypeDetails(
                azure_blob_file_list_source=AzureBlobFileListContentSource(
                    container_url=url, file_list="invoice.jsonl"
                )
            ),
            "other": ClassifierDocumentTypeDetails(
                azure_blob_file_list_source=AzureBlobFileListContentSource(
                    container_url=url, file_list="other.jsonl"
                )
            ),
        },
        allow_overwrite=True,
    )
).result()
print(f"Built classifier_id={details.classifier_id} types={list((details.doc_types or {}).keys())}")
PY

az functionapp config appsettings set \
  --name "$FUNC" --resource-group "$RG" \
  --settings "CLASSIFIER_MODEL_ID=$CLASSIFIER_ID" -o none

if [[ -f "$TF_DIR/terraform.tfvars" ]]; then
  if grep -q '^classifier_model_id' "$TF_DIR/terraform.tfvars"; then
    sed -i "s/^classifier_model_id.*/classifier_model_id     = \"$CLASSIFIER_ID\"/" "$TF_DIR/terraform.tfvars"
  else
    printf '\nclassifier_model_id     = "%s"\n' "$CLASSIFIER_ID" >> "$TF_DIR/terraform.tfvars"
  fi
fi

az functionapp restart --name "$FUNC" --resource-group "$RG" -o none
wait_function_app_settle 30
echo "Done. CLASSIFIER_MODEL_ID=$CLASSIFIER_ID"
