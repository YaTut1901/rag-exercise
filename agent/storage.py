"""Blob helpers for local Streamlit (upload PDF / delete result JSON)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from azure.storage.blob import BlobServiceClient, ContentSettings

from azure_auth import azure_credential


def _credential():
    return azure_credential()


def blob_account_url() -> str:
    url = (os.environ.get("DOCUMENTS_STORAGE__blobServiceUri") or "").strip().rstrip("/")
    if not url:
        raise RuntimeError(
            "DOCUMENTS_STORAGE__blobServiceUri is not set (App Service app setting)"
        )
    return url


def input_container() -> str:
    return (os.environ.get("INPUT_CONTAINER") or "invoices-in").strip()


def output_containers() -> tuple[str, str]:
    invoice = (os.environ.get("OUTPUT_CONTAINER_INVOICE") or "invoices-out-invoice").strip()
    read = (os.environ.get("OUTPUT_CONTAINER_READ") or "invoices-out-read").strip()
    return invoice, read


def blob_service() -> BlobServiceClient:
    return BlobServiceClient(account_url=blob_account_url(), credential=_credential())


def upload_pdf(*, blob_name: str, data: bytes, uploader_email: str) -> str:
    name = (blob_name or "").strip().lstrip("/")
    if not name.lower().endswith(".pdf"):
        raise ValueError("Only .pdf uploads are supported")
    if not data:
        raise ValueError("Empty file")
    email = (uploader_email or "").strip()
    if not email or "@" not in email:
        raise ValueError("uploaderEmail is required (used by notify)")

    container = input_container()
    client = blob_service().get_blob_client(container, name)
    client.upload_blob(
        data,
        overwrite=True,
        content_settings=ContentSettings(content_type="application/pdf"),
        metadata={"uploaderEmail": email},
    )
    return f"{container}/{name}"


@dataclass(frozen=True)
class ResultBlob:
    container: str
    name: str
    size: int
    last_modified: datetime | None


def list_result_jsons() -> list[ResultBlob]:
    svc = blob_service()
    out: list[ResultBlob] = []
    for container in output_containers():
        cc = svc.get_container_client(container)
        for blob in cc.list_blobs():
            if not str(blob.name).lower().endswith(".json"):
                continue
            out.append(
                ResultBlob(
                    container=container,
                    name=blob.name,
                    size=int(blob.size or 0),
                    last_modified=blob.last_modified,
                )
            )
    out.sort(key=lambda b: b.last_modified or datetime.min, reverse=True)
    return out


def delete_result_json(*, container: str, name: str) -> str:
    allowed = set(output_containers())
    if container not in allowed:
        raise ValueError(f"Container must be one of: {', '.join(sorted(allowed))}")
    if not name.lower().endswith(".json"):
        raise ValueError("Only result .json blobs can be deleted from the UI")
    client = blob_service().get_blob_client(container, name)
    client.delete_blob()
    return f"{container}/{name}"


def default_uploader_email() -> str:
    """Optional default from app setting; otherwise empty (user fills in UI)."""
    return (os.environ.get("DEFAULT_UPLOADER_EMAIL") or "").strip()
