"""Azure OpenAI embeddings (Managed Identity)."""

from __future__ import annotations

import logging
import os
from typing import Sequence

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

logger = logging.getLogger(__name__)

_client: AzureOpenAI | None = None


def _endpoint() -> str:
    endpoint = (os.environ.get("AZURE_OPENAI_ENDPOINT") or "").strip().rstrip("/")
    if not endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is not set")
    return endpoint


def _deployment() -> str:
    name = (os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or "").strip()
    if not name:
        raise RuntimeError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT is not set")
    return name


def _client_instance() -> AzureOpenAI:
    global _client
    if _client is not None:
        return _client
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    _client = AzureOpenAI(
        azure_endpoint=_endpoint(),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION") or "2024-10-21",
        azure_ad_token_provider=token_provider,
    )
    return _client


def embed_texts(texts: Sequence[str], *, batch_size: int = 16) -> list[list[float]]:
    """Embed texts in batches; returns vectors aligned with input order."""
    if not texts:
        return []
    client = _client_instance()
    deployment = _deployment()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = list(texts[i : i + batch_size])
        resp = client.embeddings.create(model=deployment, input=batch)
        # API may not preserve order in all versions — sort by index.
        ordered = sorted(resp.data, key=lambda d: d.index)
        vectors.extend([list(item.embedding) for item in ordered])
        logger.info(
            "Embedded batch %d–%d (%d texts) model=%s",
            i,
            i + len(batch) - 1,
            len(batch),
            deployment,
        )
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"embedding count mismatch: got {len(vectors)} for {len(texts)} texts"
        )
    return vectors
