"""Document classification via DI custom classifier (or unknown if not configured)."""

from __future__ import annotations

import logging
import os
from typing import Any

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import ClassifyDocumentRequest
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


def _di_client() -> DocumentIntelligenceClient:
    return DocumentIntelligenceClient(
        endpoint=os.environ["DOCUMENT_INTELLIGENCE_ENDPOINT"],
        credential=DefaultAzureCredential(),
    )


def classify_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    """
    Returns {documentType: invoice|other|unknown, confidence: float, modelId: str}.
    documentType unknown when model missing / low confidence / no match.
    """
    model_id = (os.environ.get("CLASSIFIER_MODEL_ID") or "").strip()
    min_conf = float(os.environ.get("CLASSIFY_MIN_CONFIDENCE") or "0.6")

    if not model_id:
        logger.warning("CLASSIFIER_MODEL_ID empty → unknown (run scripts/train_classifier.sh)")
        return {"documentType": "unknown", "confidence": 0.0, "modelId": ""}

    client = _di_client()
    poller = client.begin_classify_document(
        model_id,
        ClassifyDocumentRequest(bytes_source=pdf_bytes),
    )
    result = poller.result()
    raw = result.as_dict()

    docs = raw.get("documents") or []
    if not docs:
        return {"documentType": "unknown", "confidence": 0.0, "modelId": model_id, "raw": raw}

    top = docs[0]
    doc_type = (top.get("docType") or top.get("documentType") or "").strip().lower()
    confidence = float(top.get("confidence") or 0.0)

    if confidence < min_conf:
        return {
            "documentType": "unknown",
            "confidence": confidence,
            "modelId": model_id,
            "rawType": doc_type,
            "raw": raw,
        }

    if "invoice" in doc_type:
        mapped = "invoice"
    elif doc_type in ("other", "non-invoice", "noninvoice", "document"):
        mapped = "other"
    else:
        # custom class names: treat non-invoice labels as other if not invoice
        mapped = "other" if doc_type else "unknown"

    return {
        "documentType": mapped,
        "confidence": confidence,
        "modelId": model_id,
        "rawType": doc_type,
        "raw": raw,
    }
