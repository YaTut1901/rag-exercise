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

_VALUE_KEYS = (
    "valueString",
    "valueNumber",
    "valueInteger",
    "valueDate",
    "valueTime",
    "valuePhoneNumber",
    "valueCountryRegion",
    "valueSelectionMark",
    "valueBoolean",
)


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


def _field_value(field: dict[str, Any]) -> Any:
    """Extract a plain value from a Document Intelligence field dict."""
    for key in _VALUE_KEYS:
        if key in field and field[key] is not None:
            return field[key]
    currency = field.get("valueCurrency")
    if isinstance(currency, dict):
        amount = currency.get("amount")
        code = currency.get("currencyCode") or currency.get("currencySymbol")
        if amount is not None and code:
            return {"amount": amount, "currency": code}
        return amount
    address = field.get("valueAddress")
    if isinstance(address, dict):
        return address
    return field.get("content")


def _simplify_field(field: Any) -> Any:
    """Reduce DI field tree to value + confidence (objects/arrays recursively)."""
    if not isinstance(field, dict):
        return field

    if "valueArray" in field:
        items = [_simplify_field(item) for item in (field.get("valueArray") or [])]
        conf = field.get("confidence")
        if conf is None:
            return items
        return {"value": items, "confidence": conf}

    if "valueObject" in field:
        obj = field.get("valueObject") or {}
        simplified = {
            name: _simplify_field(child) for name, child in obj.items() if isinstance(child, dict)
        }
        conf = field.get("confidence")
        if conf is None:
            return simplified
        return {"value": simplified, "confidence": conf}

    return {
        "value": _field_value(field),
        "confidence": field.get("confidence"),
    }


def _simplify_invoice_fields(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, field in fields.items():
        if not isinstance(field, dict):
            continue
        # Line items: expose as a plain list of row objects.
        if name == "Items" and "valueArray" in field:
            rows = []
            for item in field.get("valueArray") or []:
                if isinstance(item, dict) and "valueObject" in item:
                    row = item.get("valueObject") or {}
                    rows.append(
                        {
                            k: _simplify_field(v)
                            for k, v in row.items()
                            if isinstance(v, dict)
                        }
                    )
                else:
                    rows.append(_simplify_field(item))
            out[name] = {
                "value": rows,
                "confidence": field.get("confidence"),
            }
        else:
            out[name] = _simplify_field(field)
    return out


def _pages_with_text(raw: dict[str, Any]) -> list[dict[str, Any]]:
    pages = []
    for page in raw.get("pages") or []:
        lines = page.get("lines") or []
        text = "\n".join(
            (line.get("content") or "") for line in lines if isinstance(line, dict)
        )
        pages.append(
            {
                "pageNumber": page.get("pageNumber"),
                "text": text,
            }
        )
    return pages


def normalize_result(*, model_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Build compact JSON: document pages text, or invoice fields only."""
    if model_id == "prebuilt-invoice":
        documents = raw.get("documents") or []
        fields: dict[str, Any] = {}
        if documents:
            fields = documents[0].get("fields") or {}
        return {
            "type": "invoice",
            "fields": _simplify_invoice_fields(fields),
        }

    return {
        "type": "document",
        "pages": _pages_with_text(raw),
    }


def save_json(container_name: str, blob_name: str, payload: dict[str, Any]) -> tuple[str, bytes]:
    """Upload JSON; return (container/blob path, exact UTF-8 bytes written)."""
    service = _blob_service()
    container = service.get_container_client(container_name)
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    blob = container.get_blob_client(blob_name)
    blob.upload_blob(data, overwrite=True, content_type="application/json")
    logger.info("Wrote result to %s/%s (%d bytes)", container_name, blob_name, len(data))
    return f"{container_name}/{blob_name}", data


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
        payload = normalize_result(model_id=model_id, raw=raw)
        out_name = pdf_name_to_json_name(source_blob)
        save_json(output_container, out_name, payload)
        detail = (
            f"fields={len(payload.get('fields') or {})}"
            if payload.get("type") == "invoice"
            else f"pages={len(payload.get('pages') or [])}"
        )
        logger.info(
            "Finished OCR model=%s source=%s duration=%.3fs %s",
            model_id,
            source_blob,
            duration,
            detail,
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
