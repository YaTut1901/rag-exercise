"""RAG tool over Postgres doc_chunks (company data)."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from db import search_doc_chunks
from embeddings import embed_texts

logger = logging.getLogger(__name__)


@tool
def company_rag(query: str, k: int = 5) -> str:
    """Search company documents (RAG). Use for questions about company policies,
    products, overview text, and other non-invoice PDFs indexed in doc_chunks.

    Args:
        query: Natural-language search query.
        k: Number of chunks to return (1–20).
    """
    q = (query or "").strip()
    if not q:
        return json.dumps({"error": "empty query", "chunks": []}, ensure_ascii=False)

    k = max(1, min(int(k or 5), 20))
    vectors = embed_texts([q])
    rows = search_doc_chunks(vectors[0], k=k)
    chunks = [
        {
            "id": r.get("id"),
            "source_file": r.get("source_file"),
            "page_number": r.get("page_number"),
            "chunk_index": r.get("chunk_index"),
            "title": r.get("title"),
            "score": r.get("score"),
            "content": r.get("content"),
        }
        for r in rows
    ]
    logger.info("company_rag query=%r hits=%d", q[:80], len(chunks))
    return json.dumps({"query": q, "chunks": chunks}, ensure_ascii=False)
