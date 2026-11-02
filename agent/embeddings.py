"""Query embeddings for RAG (Azure OpenAI)."""

from __future__ import annotations

import os
from typing import Sequence

from azure_auth import make_openai_client

_client = None


def _deployment() -> str:
    name = (os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or "").strip()
    if not name:
        raise RuntimeError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT is not set")
    return name


def embed_texts(texts: Sequence[str], *, batch_size: int = 16) -> list[list[float]]:
    global _client
    if not texts:
        return []
    if _client is None:
        _client = make_openai_client()
    deployment = _deployment()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = list(texts[i : i + batch_size])
        resp = _client.embeddings.create(model=deployment, input=batch)
        ordered = sorted(resp.data, key=lambda d: d.index)
        vectors.extend([list(item.embedding) for item in ordered])
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"embedding count mismatch: got {len(vectors)} for {len(texts)} texts"
        )
    return vectors
