"""Queue event helpers."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from shared.storage import queue_client

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_event_id() -> str:
    return str(uuid.uuid4())


def enqueue(queue_env_key: str, payload: dict[str, Any]) -> None:
    queue_name = os.environ[queue_env_key]
    body = json.dumps(payload, ensure_ascii=False)
    queue_client(queue_name).send_message(body)
    logger.info("Enqueued %s → %s", payload.get("kind") or payload.get("type"), queue_name)


def parse_queue_json(msg_body: str | bytes) -> dict[str, Any]:
    if isinstance(msg_body, bytes):
        msg_body = msg_body.decode("utf-8")
    data = json.loads(msg_body)
    # Event Grid → Storage Queue may wrap the event as a list or single object
    if isinstance(data, list) and data:
        data = data[0]
    return data


def parse_blob_url(url: str) -> tuple[str, str]:
    """Return (container, blob_name) from https://account.blob.core.windows.net/container/name."""
    # strip query
    url = url.split("?", 1)[0]
    marker = ".blob.core.windows.net/"
    idx = url.find(marker)
    if idx < 0:
        raise ValueError(f"Not a blob URL: {url}")
    path = url[idx + len(marker) :]
    container, _, blob = path.partition("/")
    return container, blob
