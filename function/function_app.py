"""Lab-2 event-driven PDF pipeline (queues + Event Grid)."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import azure.functions as func

from shared.classify import classify_pdf
from shared.dochashes import (
    get_by_raw_hash,
    set_processed_hash,
    try_insert_raw,
    delete_by_processed_hash,
)
from shared.events import (
    enqueue,
    new_event_id,
    parse_blob_url,
    parse_queue_json,
    utc_now,
)
from shared.hashes import sha256_hex
from shared.notify_email import send_email
from shared.ocr import analyze_document, normalize_result, save_json
from shared.storage import (
    blob_exists,
    blob_read_web_url,
    delete_blob,
    download_blob_bytes,
    get_blob_metadata,
    undelete_blob,
    upload_bytes,
)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
logger = logging.getLogger(__name__)


def _max_dequeue() -> int:
    return int(os.environ.get("QUEUE_MAX_DEQUEUE_COUNT") or "5")


def _base_event(**kwargs: Any) -> dict[str, Any]:
    payload = {
        "eventId": new_event_id(),
        "enqueuedAtUtc": utc_now(),
    }
    payload.update(kwargs)
    return payload


def _raw_hash_pdf_name(raw_hash: str) -> str:
    return f"{raw_hash}.pdf"


def _raw_hash_json_name(raw_hash: str) -> str:
    return f"{raw_hash}.json"


def _output_containers() -> list[str]:
    names: list[str] = []
    for key in ("OUTPUT_CONTAINER_INVOICE", "OUTPUT_CONTAINER_READ"):
        value = (os.environ.get(key) or "").strip()
        if value and value not in names:
            names.append(value)
    return names


def _find_result_container(raw_hash: str) -> str | None:
    """Locate out container that holds deterministic {rawHash}.json (no path in table)."""
    json_name = _raw_hash_json_name(raw_hash)
    for container in _output_containers():
        if blob_exists(container, json_name):
            return container
    return None


def _extract_ok_message(
    *,
    stage: str,
    source_blob: str,
    result_container: str,
    raw_hash: str,
    model_id: str,
    duration_sec: float | None = None,
    duplicate: bool = False,
) -> str:
    pdf_name = _raw_hash_pdf_name(raw_hash)
    json_name = _raw_hash_json_name(raw_hash)
    pdf_url = blob_read_web_url(result_container, pdf_name)
    json_url = blob_read_web_url(result_container, json_name)
    timing = f", {duration_sec:.2f}s" if duration_sec is not None else ""
    prefix = (
        "Extract OK (duplicate, existing result)"
        if duplicate
        else f"Extract OK ({stage})"
    )
    return (
        f"{prefix}: {source_blob} → {result_container}/{json_name} "
        f"(model={model_id}{timing})\n"
        f"Source PDF: {pdf_url}\n"
        f"Result JSON: {json_url}"
    )


def _enqueue_notify(
    *,
    kind: str,
    message: str,
    blob_name: str,
    raw_hash: str,
    uploader_email: str,
    stage: str,
    correlation_id: str,
) -> None:
    enqueue(
        "QUEUE_NOTIFY",
        _base_event(
            type="notify",
            kind=kind,
            message=message,
            blobName=blob_name,
            rawHash=raw_hash,
            uploaderEmail=uploader_email,
            stage=stage,
            correlationId=correlation_id,
        ),
    )


def _notify_duplicate_and_delete(
    *,
    container: str,
    blob_name: str,
    raw_hash: str,
    uploader_email: str,
    correlation_id: str,
) -> None:
    result_container = _find_result_container(raw_hash)
    if result_container:
        message = _extract_ok_message(
            stage="duplicate",
            source_blob=blob_name,
            result_container=result_container,
            raw_hash=raw_hash,
            model_id="(cached)",
            duplicate=True,
        )
    else:
        message = (
            f"Extract OK (duplicate, existing result): {blob_name} "
            f"(rawHash={raw_hash[:12]}…; result blob not found in out containers)"
        )

    _enqueue_notify(
        kind="success",
        message=message,
        blob_name=blob_name,
        raw_hash=raw_hash,
        uploader_email=uploader_email,
        stage="duplicate",
        correlation_id=correlation_id,
    )
    _enqueue_delete_pdf(
        container=container,
        blob_name=blob_name,
        raw_hash=raw_hash,
        reason="duplicate",
        uploader_email=uploader_email,
        correlation_id=correlation_id,
    )


def _enqueue_delete_pdf(
    *,
    container: str,
    blob_name: str,
    raw_hash: str,
    reason: str,
    uploader_email: str,
    correlation_id: str,
) -> None:
    enqueue(
        "QUEUE_DELETE_PDF",
        _base_event(
            type="delete-pdf",
            container=container,
            blobName=blob_name,
            rawHash=raw_hash,
            reason=reason,
            uploaderEmail=uploader_email,
            correlationId=correlation_id,
        ),
    )


# ---------------------------------------------------------------------------
# 1) Ingress — Event Grid BlobCreated via q-ingress
# ---------------------------------------------------------------------------
@app.queue_trigger(
    arg_name="msg",
    queue_name="%QUEUE_INGRESS%",
    connection="DOCUMENTS_STORAGE",
)
def ingress(msg: func.QueueMessage) -> None:
    data = parse_queue_json(msg.get_body())
    correlation_id = data.get("id") or new_event_id()

    event_data = data.get("data") or data
    url = event_data.get("url") or ""
    if not url:
        # already an internal event?
        url = data.get("blobUrl") or ""
    if not url:
        logger.error("ingress: no blob url in message: %s", data)
        return

    container, blob_name = parse_blob_url(url)
    if not blob_name.lower().endswith(".pdf"):
        logger.info("ingress: skip non-pdf %s", blob_name)
        return

    input_container = os.environ.get("INPUT_CONTAINER", "invoices-in")
    if container != input_container:
        logger.info("ingress: skip container %s", container)
        return

    pdf_bytes = download_blob_bytes(container, blob_name)
    raw_hash = sha256_hex(pdf_bytes)
    metadata = get_blob_metadata(container, blob_name)
    uploader_email = (
        metadata.get("uploaderEmail")
        or metadata.get("uploaderemail")
        or ""
    )

    existing = get_by_raw_hash(raw_hash)
    if existing and (existing.get("processedHash") or "").strip():
        logger.info("ingress: duplicate processed rawHash=%s → notify + delete-pdf", raw_hash)
        _notify_duplicate_and_delete(
            container=container,
            blob_name=blob_name,
            raw_hash=raw_hash,
            uploader_email=uploader_email,
            correlation_id=correlation_id,
        )
        return

    if existing is None:
        inserted = try_insert_raw(raw_hash)
        if not inserted:
            # race: re-read
            existing = get_by_raw_hash(raw_hash)
            if existing and (existing.get("processedHash") or "").strip():
                logger.info(
                    "ingress: duplicate (race) processed rawHash=%s → notify + delete-pdf",
                    raw_hash,
                )
                _notify_duplicate_and_delete(
                    container=container,
                    blob_name=blob_name,
                    raw_hash=raw_hash,
                    uploader_email=uploader_email,
                    correlation_id=correlation_id,
                )
                return

    classification = classify_pdf(pdf_bytes)
    doc_type = classification["documentType"]
    confidence = classification.get("confidence", 0.0)

    extract_payload = _base_event(
        type=f"extract-{doc_type if doc_type != 'other' else 'read'}",
        container=container,
        blobName=blob_name,
        rawHash=raw_hash,
        uploaderEmail=uploader_email,
        documentType=doc_type,
        confidence=confidence,
        classifierModelId=classification.get("modelId") or "",
        correlationId=correlation_id,
    )

    if doc_type == "invoice":
        extract_payload["type"] = "extract-invoice"
        enqueue("QUEUE_EXTRACT_INVOICE", extract_payload)
    elif doc_type == "other":
        extract_payload["type"] = "extract-read"
        enqueue("QUEUE_EXTRACT_READ", extract_payload)
    else:
        extract_payload["type"] = "extract-unknown"
        enqueue("QUEUE_EXTRACT_UNKNOWN", extract_payload)

    logger.info(
        "ingress: routed %s as %s conf=%.3f uploader=%s",
        blob_name,
        doc_type,
        confidence,
        uploader_email or "(none)",
    )


# ---------------------------------------------------------------------------
# 2a / 2b) Extract invoice / read
# ---------------------------------------------------------------------------
def _run_extract(
    msg: func.QueueMessage,
    *,
    model_id: str,
    output_container_env: str,
    stage: str,
) -> None:
    data = parse_queue_json(msg.get_body())
    dequeue = msg.dequeue_count or 1
    max_dq = _max_dequeue()

    container = data["container"]
    blob_name = data["blobName"]
    raw_hash = data["rawHash"]
    uploader_email = data.get("uploaderEmail") or ""
    correlation_id = data.get("correlationId") or new_event_id()
    output_container = os.environ[output_container_env]

    try:
        pdf_bytes = download_blob_bytes(container, blob_name)
        started = time.perf_counter()
        raw = analyze_document(model_id, pdf_bytes)
        duration = time.perf_counter() - started
        payload = normalize_result(
            source_blob=blob_name,
            model_id=model_id,
            duration_sec=duration,
            raw=raw,
        )
        # Deterministic names from content hash — no result path in docHashes.
        pdf_out = _raw_hash_pdf_name(raw_hash)
        json_out = _raw_hash_json_name(raw_hash)
        upload_bytes(
            output_container,
            pdf_out,
            pdf_bytes,
            content_type="application/pdf",
        )
        _, json_bytes = save_json(output_container, json_out, payload)
        processed_hash = sha256_hex(json_bytes)
        set_processed_hash(raw_hash, processed_hash)

        message = _extract_ok_message(
            stage=stage,
            source_blob=blob_name,
            result_container=output_container,
            raw_hash=raw_hash,
            model_id=model_id,
            duration_sec=duration,
        )
        _enqueue_notify(
            kind="success",
            message=message,
            blob_name=blob_name,
            raw_hash=raw_hash,
            uploader_email=uploader_email,
            stage=stage,
            correlation_id=correlation_id,
        )
        _enqueue_delete_pdf(
            container=container,
            blob_name=blob_name,
            raw_hash=raw_hash,
            reason="extracted",
            uploader_email=uploader_email,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        logger.exception("extract failed stage=%s blob=%s", stage, blob_name)
        if dequeue >= max_dq:
            _enqueue_notify(
                kind="extract_failed",
                message=(
                    f"Extract failed after retries ({stage}): {blob_name} — {exc}"
                ),
                blob_name=blob_name,
                raw_hash=raw_hash,
                uploader_email=uploader_email,
                stage=stage,
                correlation_id=correlation_id,
            )
        raise


@app.queue_trigger(
    arg_name="msg",
    queue_name="%QUEUE_EXTRACT_INVOICE%",
    connection="DOCUMENTS_STORAGE",
)
def extract_invoice(msg: func.QueueMessage) -> None:
    _run_extract(
        msg,
        model_id="prebuilt-invoice",
        output_container_env="OUTPUT_CONTAINER_INVOICE",
        stage="extract_invoice",
    )


@app.queue_trigger(
    arg_name="msg",
    queue_name="%QUEUE_EXTRACT_READ%",
    connection="DOCUMENTS_STORAGE",
)
def extract_read(msg: func.QueueMessage) -> None:
    _run_extract(
        msg,
        model_id="prebuilt-read",
        output_container_env="OUTPUT_CONTAINER_READ",
        stage="extract_read",
    )


# ---------------------------------------------------------------------------
# 3) Extract unknown
# ---------------------------------------------------------------------------
@app.queue_trigger(
    arg_name="msg",
    queue_name="%QUEUE_EXTRACT_UNKNOWN%",
    connection="DOCUMENTS_STORAGE",
)
def extract_unknown(msg: func.QueueMessage) -> None:
    data = parse_queue_json(msg.get_body())
    blob_name = data["blobName"]
    container = data["container"]
    raw_hash = data["rawHash"]
    uploader_email = data.get("uploaderEmail") or ""
    correlation_id = data.get("correlationId") or new_event_id()

    message = f"Unknown document format, skipped extract: {blob_name}"
    logger.warning(message)
    _enqueue_notify(
        kind="format_error",
        message=message,
        blob_name=blob_name,
        raw_hash=raw_hash,
        uploader_email=uploader_email,
        stage="extract_unknown",
        correlation_id=correlation_id,
    )
    _enqueue_delete_pdf(
        container=container,
        blob_name=blob_name,
        raw_hash=raw_hash,
        reason="unknown",
        uploader_email=uploader_email,
        correlation_id=correlation_id,
    )


# ---------------------------------------------------------------------------
# 4) Delete PDF from invoices-in
# ---------------------------------------------------------------------------
@app.queue_trigger(
    arg_name="msg",
    queue_name="%QUEUE_DELETE_PDF%",
    connection="DOCUMENTS_STORAGE",
)
def delete_pdf_fn(msg: func.QueueMessage) -> None:
    data = parse_queue_json(msg.get_body())
    container = data["container"]
    blob_name = data["blobName"]
    reason = data.get("reason") or ""
    try:
        delete_blob(container, blob_name)
        logger.info("Deleted PDF %s/%s reason=%s", container, blob_name, reason)
    except Exception:
        logger.exception("delete_pdf failed for %s/%s", container, blob_name)
        raise


# ---------------------------------------------------------------------------
# 5) Delete result JSON → clear docHashes by processedHash
# ---------------------------------------------------------------------------
@app.queue_trigger(
    arg_name="msg",
    queue_name="%QUEUE_DELETE_RESULT%",
    connection="DOCUMENTS_STORAGE",
)
def delete_result(msg: func.QueueMessage) -> None:
    data = parse_queue_json(msg.get_body())
    event_data = data.get("data") or data
    url = event_data.get("url") or ""
    if not url:
        logger.error("delete_result: no url: %s", data)
        return

    container, blob_name = parse_blob_url(url)
    # Only JSON results clear docHashes; companion {rawHash}.pdf deletes are ignored.
    if not blob_name.lower().endswith(".json"):
        logger.info("delete_result: skip non-json %s/%s", container, blob_name)
        return

    # Soft-deleted: undelete → download → clear docHashes → soft-delete again.
    # Soft-delete re-fires BlobDeleted; if the table row is already gone, do NOT
    # soft-delete again (would loop). Echo pass finds no row and returns without
    # delete_blob.
    try:
        undelete_blob(container, blob_name)
    except Exception:
        logger.exception("undelete failed %s/%s (may already be gone)", container, blob_name)
        return

    try:
        content = download_blob_bytes(container, blob_name)
        processed_hash = sha256_hex(content)
        found = delete_by_processed_hash(processed_hash)
        if not found:
            logger.warning(
                "delete_result: no table row for processedHash=%s blob=%s (echo; skip re-delete)",
                processed_hash,
                blob_name,
            )
            return
        delete_blob(container, blob_name)
        logger.info(
            "delete_result: cleared docHashes processedHash=%s and re-deleted %s/%s",
            processed_hash,
            container,
            blob_name,
        )
    except Exception:
        logger.exception("delete_result failed for %s/%s", container, blob_name)
        raise


# ---------------------------------------------------------------------------
# 6) Notify uploader by email
# ---------------------------------------------------------------------------
@app.queue_trigger(
    arg_name="msg",
    queue_name="%QUEUE_NOTIFY%",
    connection="DOCUMENTS_STORAGE",
)
def notify(msg: func.QueueMessage) -> None:
    data = parse_queue_json(msg.get_body())
    kind = data.get("kind") or "info"
    message = data.get("message") or ""
    uploader_email = data.get("uploaderEmail") or ""
    blob_name = data.get("blobName") or ""

    subject = {
        "success": f"[rag-exercise] Extract OK: {blob_name}",
        "format_error": f"[rag-exercise] Unknown format: {blob_name}",
        "extract_failed": f"[rag-exercise] Extract FAILED: {blob_name}",
    }.get(kind, f"[rag-exercise] {kind}: {blob_name}")

    logger.info("notify kind=%s to=%s msg=%s", kind, uploader_email or "(none)", message)
    send_email(to_address=uploader_email, subject=subject, body=message)
