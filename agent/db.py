"""Postgres access for the agent (RAG search + readonly invoice SQL)."""

from __future__ import annotations

import os
import re
from decimal import Decimal
from typing import Any

_ALLOWED_TABLES = frozenset({"invoices", "invoice_line_items"})
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"copy|call|execute|do|comment|vacuum|analyze|refresh|merge|"
    r"set\s+role|set\s+session|pg_sleep)\b",
    re.IGNORECASE,
)
_TABLE_REF = re.compile(
    r"\b(?:from|join|update|into|table)\s+([a-zA-Z_][\w.]*)",
    re.IGNORECASE,
)
_LIMIT = re.compile(r"\blimit\b", re.IGNORECASE)
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _psycopg():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg, dict_row


def _database_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set (App Service app setting)")
    return url


def _connect():
    psycopg, dict_row = _psycopg()
    return psycopg.connect(_database_url(), row_factory=dict_row)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in values) + "]"


def search_doc_chunks(
    query_embedding: list[float],
    *,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Nearest-neighbor search over doc_chunks (cosine via pgvector)."""
    limit = max(1, min(int(k), 20))
    emb = _vector_literal(query_embedding)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
              id,
              raw_hash,
              source_file,
              page_number,
              chunk_index,
              content,
              title,
              (1 - (embedding <=> %s::vector)) AS score
            FROM doc_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (emb, emb, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.get("score") is not None:
            item["score"] = float(item["score"])
        out.append(item)
    return out


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def validate_readonly_sql(sql: str) -> str:
    """
    Normalize and validate model-generated SQL.
    Raises ValueError with a message the LLM can use to retry.
    """
    text = (sql or "").strip()
    if not text:
        raise ValueError("SQL is empty")

    # Single statement only.
    cleaned = text.rstrip().rstrip(";").strip()
    if ";" in cleaned:
        raise ValueError("Only a single SQL statement is allowed (no semicolons)")

    if _FORBIDDEN.search(cleaned):
        raise ValueError(
            "Only read-only SELECT/WITH queries are allowed "
            "(no INSERT/UPDATE/DELETE/DDL/admin statements)"
        )

    head = re.sub(r"^\s*", "", cleaned, flags=re.IGNORECASE)
    if not re.match(r"^(with|select)\b", head, flags=re.IGNORECASE):
        raise ValueError("Query must start with SELECT or WITH")

    tables: set[str] = set()
    for match in _TABLE_REF.finditer(cleaned):
        raw = match.group(1)
        name = raw.split(".")[-1].lower()
        tables.add(name)

    if not tables:
        raise ValueError(
            "Could not detect table names; query invoices and/or invoice_line_items"
        )

    unknown = sorted(tables - _ALLOWED_TABLES)
    if unknown:
        raise ValueError(
            "Only these tables are allowed: invoices, invoice_line_items. "
            f"Forbidden or unknown: {', '.join(unknown)}"
        )

    if not _LIMIT.search(cleaned):
        cleaned = f"{cleaned}\nLIMIT {_DEFAULT_LIMIT}"

    return cleaned


def run_readonly_sql(sql: str) -> dict[str, Any]:
    """
    Execute validated readonly SQL.
    Returns {ok, columns, rows, row_count} or raises ValueError / DB errors.
    """
    cleaned = validate_readonly_sql(sql)
    with _connect() as conn:
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout = '5000ms'")
            cur = conn.execute(cleaned)
            rows_raw = cur.fetchall()
            columns = [d.name for d in (cur.description or [])]

    rows = [{k: _jsonable(v) for k, v in dict(r).items()} for r in rows_raw]
    if len(rows) > _MAX_LIMIT:
        rows = rows[:_MAX_LIMIT]
    return {
        "ok": True,
        "sql": cleaned,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }
