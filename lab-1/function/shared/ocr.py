"""Document Intelligence helpers and JSON normalization."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, DocumentContentFormat
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)


def _di_client() -> DocumentIntelligenceClient:
    endpoint = os.environ["DOCUMENT_INTELLIGENCE_ENDPOINT"]
    credential = DefaultAzureCredential()
    return DocumentIntelligenceClient(endpoint=endpoint, credential=credential)


def _blob_service() -> BlobServiceClient:
    account_url = os.environ["DOCUMENTS_STORAGE__blobServiceUri"]
    credential = DefaultAzureCredential()
    return BlobServiceClient(account_url=account_url, credential=credential)


def analyze_document(model_id: str, pdf_bytes: bytes) -> dict[str, Any]:
    """Run Document Intelligence (async poller) and return a serializable dict."""
    client = _di_client()
    poller = client.begin_analyze_document(
        model_id,
        AnalyzeDocumentRequest(bytes_source=pdf_bytes),
        output_content_format=DocumentContentFormat.TEXT,
    )
    result = poller.result()
    return result.as_dict()


def normalize_result(
    *,
    source_blob: str,
    model_id: str,
    duration_sec: float,
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Keep pages + content for lab-3 citations; keep full SDK payload under raw."""
    raw_pages = raw.get("pages") or []
    pages = []
    for page in raw_pages:
        pages.append(
            {
                "pageNumber": page.get("pageNumber"),
                "width": page.get("width"),
                "height": page.get("height"),
                "unit": page.get("unit"),
                "lines": [
                    {
                        "content": line.get("content"),
                        "polygon": line.get("polygon"),
                    }
                    for line in (page.get("lines") or [])
                ],
            }
        )

    documents = raw.get("documents") or []
    fields: dict[str, Any] = {}
    if documents:
        fields = documents[0].get("fields") or {}

    return {
        "sourceBlob": source_blob,
        "modelId": model_id,
        "processedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "durationSeconds": round(duration_sec, 3),
        "pageCount": len(raw_pages),
        "content": raw.get("content"),
        "pages": pages,
        "invoiceFields": fields,
        "raw": raw,
    }


def save_json(container_name: str, blob_name: str, payload: dict[str, Any]) -> str:
    service = _blob_service()
    container = service.get_container_client(container_name)
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    blob = container.get_blob_client(blob_name)
    blob.upload_blob(data, overwrite=True, content_type="application/json")
    logger.info("Wrote result to %s/%s (%d bytes)", container_name, blob_name, len(data))
    return f"{container_name}/{blob_name}"


def pdf_name_to_json_name(blob_name: str) -> str:
    base = blob_name.rsplit("/", 1)[-1]
    if base.lower().endswith(".pdf"):
        return base[:-4] + ".json"
    return base + ".json"


def process_pdf(
    *,
    pdf_bytes: bytes,
    source_blob: str,
    model_id: str,
    output_container: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    logger.info(
        "Start OCR model=%s source=%s size=%d bytes",
        model_id,
        source_blob,
        len(pdf_bytes),
    )
    try:
        raw = analyze_document(model_id, pdf_bytes)
        duration = time.perf_counter() - started
        payload = normalize_result(
            source_blob=source_blob,
            model_id=model_id,
            duration_sec=duration,
            raw=raw,
        )
        out_name = pdf_name_to_json_name(source_blob)
        save_json(output_container, out_name, payload)
        logger.info(
            "Finished OCR model=%s source=%s duration=%.3fs pages=%s",
            model_id,
            source_blob,
            duration,
            payload.get("pageCount"),
        )
        return payload
    except Exception:
        duration = time.perf_counter() - started
        logger.exception(
            "OCR failed model=%s source=%s duration=%.3fs",
            model_id,
            source_blob,
            duration,
        )
        raise
