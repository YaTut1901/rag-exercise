"""Table Storage helpers for rawHash / processedHash."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import UpdateMode

from shared.storage import table_client

logger = logging.getLogger(__name__)

PARTITION = "doc"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_by_raw_hash(raw_hash: str) -> dict[str, Any] | None:
    try:
        entity = table_client().get_entity(partition_key=PARTITION, row_key=raw_hash)
        return dict(entity)
    except ResourceNotFoundError:
        return None


def try_insert_raw(raw_hash: str) -> bool:
    """Insert new row with empty processedHash. Returns False if rawHash already exists."""
    entity = {
        "PartitionKey": PARTITION,
        "RowKey": raw_hash,
        "rawHash": raw_hash,
        "processedHash": "",
        "updatedAtUtc": _now(),
    }
    try:
        table_client().create_entity(entity)
        return True
    except ResourceExistsError:
        return False


def set_processed_hash(raw_hash: str, processed_hash: str) -> None:
    client = table_client()
    entity = client.get_entity(partition_key=PARTITION, row_key=raw_hash)
    entity["processedHash"] = processed_hash
    entity["updatedAtUtc"] = _now()
    client.update_entity(entity=entity, mode=UpdateMode.REPLACE)


def delete_by_processed_hash(processed_hash: str) -> bool:
    """Scan partition for processedHash match and delete. Returns True if deleted."""
    client = table_client()
    # Table Storage filter
    entities = client.query_entities(
        query_filter="PartitionKey eq @pk and processedHash eq @ph",
        parameters={"pk": PARTITION, "ph": processed_hash},
    )
    deleted = False
    for ent in entities:
        client.delete_entity(partition_key=ent["PartitionKey"], row_key=ent["RowKey"])
        logger.info("Deleted docHashes row rawHash=%s processedHash=%s", ent["RowKey"], processed_hash)
        deleted = True
    return deleted
