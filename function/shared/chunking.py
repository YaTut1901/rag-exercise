"""Per-page text chunking with overlap (lab-3)."""

from __future__ import annotations

import os
import re
from typing import Any


def _chunk_size_tokens() -> int:
    return int(os.environ.get("CHUNK_SIZE_TOKENS") or "800")


def _overlap_ratio() -> float:
    return float(os.environ.get("CHUNK_OVERLAP_RATIO") or "0.15")


def _approx_tokens(text: str) -> int:
    # Cheap token estimate without tiktoken (~4 chars/token for mixed text).
    return max(1, (len(text) + 3) // 4)


def _chars_for_tokens(tokens: int) -> int:
    return max(1, tokens * 4)


def chunk_page_text(text: str, *, page_number: int) -> list[dict[str, Any]]:
    """Split one page into overlapping chunks; keep page_number on each."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    size_tok = _chunk_size_tokens()
    overlap_tok = max(0, int(size_tok * _overlap_ratio()))
    size_chars = _chars_for_tokens(size_tok)
    overlap_chars = _chars_for_tokens(overlap_tok)
    step = max(1, size_chars - overlap_chars)

    if _approx_tokens(cleaned) <= size_tok:
        return [
            {
                "page_number": page_number,
                "chunk_index": 0,
                "content": cleaned,
            }
        ]

    chunks: list[dict[str, Any]] = []
    start = 0
    idx = 0
    length = len(cleaned)
    while start < length:
        end = min(length, start + size_chars)
        # Prefer breaking on whitespace near the window end.
        if end < length:
            window = cleaned[start:end]
            soft = max(window.rfind("\n"), window.rfind(" "))
            if soft > size_chars * 0.5:
                end = start + soft
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(
                {
                    "page_number": page_number,
                    "chunk_index": idx,
                    "content": piece,
                }
            )
            idx += 1
        if end >= length:
            break
        start = max(end - overlap_chars, start + 1)

    return chunks


def chunk_document_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chunk each page independently (overlap only within a page)."""
    out: list[dict[str, Any]] = []
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        page_number = int(page.get("pageNumber") or page.get("page_number") or 0)
        text = page.get("text") or ""
        out.extend(chunk_page_text(str(text), page_number=page_number))
    return out


def infer_title(pages: list[dict[str, Any]]) -> str | None:
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        text = (page.get("text") or "").strip()
        if not text:
            continue
        first = text.splitlines()[0].strip()
        first = re.sub(r"\s+", " ", first)
        if first:
            return first[:200]
    return None
