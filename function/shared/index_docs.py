"""Index Company Data JSON into Postgres doc_chunks (pipeline hook)."""

from __future__ import annotations

import logging
from typing import Any

from shared.chunking import chunk_document_pages, infer_title
from shared.db import replace_doc_chunks
from shared.embeddings import embed_texts

logger = logging.getLogger(__name__)


def index_document_payload(
    *,
    raw_hash: str,
    source_file: str,
    payload: dict[str, Any],
) -> int:
    """
    Chunk pages from normalized document JSON, embed, replace rows for raw_hash.
    Returns number of chunks written.
    """
    if payload.get("type") != "document":
        logger.info("Skip indexing non-document payload type=%s", payload.get("type"))
        return 0

    pages = payload.get("pages") or []
    chunks = chunk_document_pages(pages)
    if not chunks:
        logger.warning("No text chunks for raw_hash=%s source=%s", raw_hash[:12], source_file)
        replace_doc_chunks(raw_hash=raw_hash, rows=[])
        return 0

    title = infer_title(pages)
    texts = [c["content"] for c in chunks]
    vectors = embed_texts(texts)

    rows = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        page_number = int(chunk["page_number"])
        chunk_index = int(chunk["chunk_index"])
        rows.append(
            {
                "id": f"{raw_hash}-{page_number}-{chunk_index}",
                "raw_hash": raw_hash,
                "source_file": source_file,
                "page_number": page_number,
                "chunk_index": chunk_index,
                "content": chunk["content"],
                "embedding": vector,
                "title": title,
                "doc_date": None,
            }
        )

    replace_doc_chunks(raw_hash=raw_hash, rows=rows)
    logger.info(
        "Indexed document raw_hash=%s source=%s chunks=%d",
        raw_hash[:12],
        source_file,
        len(rows),
    )
    return len(rows)
