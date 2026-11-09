"""Blob / queue / table clients via Managed Identity."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas
from azure.storage.queue import (
    QueueClient,
    QueueServiceClient,
    TextBase64DecodePolicy,
    TextBase64EncodePolicy,
)
from azure.data.tables import TableClient, TableServiceClient

logger = logging.getLogger(__name__)


def _credential() -> DefaultAzureCredential:
    return DefaultAzureCredential()


def blob_service() -> BlobServiceClient:
    return BlobServiceClient(
        account_url=os.environ["DOCUMENTS_STORAGE__blobServiceUri"],
        credential=_credential(),
    )


def queue_service() -> QueueServiceClient:
    return QueueServiceClient(
        account_url=os.environ["DOCUMENTS_STORAGE__queueServiceUri"],
        credential=_credential(),
    )


def table_service() -> TableServiceClient:
    # azure-data-tables uses `endpoint` (unlike blob/queue `account_url`)
    return TableServiceClient(
        endpoint=os.environ["DOCUMENTS_STORAGE__tableServiceUri"],
        credential=_credential(),
    )


def queue_client(queue_name: str) -> QueueClient:
    # Match Azure Functions queue extension default (base64), same as Event Grid → Storage Queue.
    return queue_service().get_queue_client(
        queue_name,
        message_encode_policy=TextBase64EncodePolicy(),
        message_decode_policy=TextBase64DecodePolicy(),
    )


def table_client(table_name: str | None = None) -> TableClient:
    name = table_name or os.environ["TABLE_DOC_HASHES"]
    return table_service().get_table_client(name)


def download_blob_bytes(container: str, blob_name: str) -> bytes:
    client = blob_service().get_blob_client(container, blob_name)
    return client.download_blob().readall()


def get_blob_metadata(container: str, blob_name: str) -> dict[str, str]:
    client = blob_service().get_blob_client(container, blob_name)
    props = client.get_blob_properties()
    return dict(props.metadata or {})


def delete_blob(container: str, blob_name: str) -> None:
    client = blob_service().get_blob_client(container, blob_name)
    client.delete_blob()


def undelete_blob(container: str, blob_name: str) -> None:
    client = blob_service().get_blob_client(container, blob_name)
    client.undelete_blob()


def blob_exists(container: str, blob_name: str) -> bool:
    client = blob_service().get_blob_client(container, blob_name)
    return bool(client.exists())


def upload_bytes(
    container: str,
    blob_name: str,
    data: bytes,
    *,
    content_type: str,
) -> None:
    client = blob_service().get_blob_client(container, blob_name)
    client.upload_blob(data, overwrite=True, content_type=content_type)


def blob_https_url(container: str, blob_name: str) -> str:
    """Stable HTTPS URL (private container — needs auth / SAS to open in a browser)."""
    base = os.environ["DOCUMENTS_STORAGE__blobServiceUri"].rstrip("/")
    # quote path segments but keep slashes in blob name
    encoded = "/".join(quote(part, safe="") for part in blob_name.split("/"))
    return f"{base}/{container}/{encoded}"


def blob_read_web_url(container: str, blob_name: str, *, ttl_hours: int | None = None) -> str:
    """
    Browser-openable link: user-delegation read SAS when possible, else plain HTTPS URL.
    Default TTL follows blob soft-delete retention (BLOB_SOFT_DELETE_DAYS) or 7d.
    """
    https = blob_https_url(container, blob_name)
    if ttl_hours is None:
        ttl_hours = int(os.environ.get("BLOB_SOFT_DELETE_DAYS") or "7") * 24
    try:
        service = blob_service()
        account_name = service.account_name
        if not account_name:
            # parse from URL: https://{account}.blob.core.windows.net
            host = os.environ["DOCUMENTS_STORAGE__blobServiceUri"].split("//", 1)[-1]
            account_name = host.split(".", 1)[0]
        now = datetime.now(timezone.utc)
        key = service.get_user_delegation_key(now - timedelta(minutes=5), now + timedelta(hours=ttl_hours))
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=container,
            blob_name=blob_name,
            user_delegation_key=key,
            permission=BlobSasPermissions(read=True),
            expiry=now + timedelta(hours=ttl_hours),
            start=now - timedelta(minutes=5),
        )
        return f"{https}?{sas}"
    except Exception:
        logger.exception(
            "SAS failed for %s/%s — falling back to plain HTTPS URL",
            container,
            blob_name,
        )
        return https
