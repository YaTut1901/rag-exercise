"""PostgreSQL helpers: invoice columns + RAG doc_chunks (pgvector)."""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)


def _psycopg():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg, dict_row

_schema_ready = False

_INVOICE_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS invoices (
      processed_hash  text PRIMARY KEY,
      raw_hash        text NOT NULL,
      vendor_name     text,
      customer_name   text,
      invoice_id      text,
      invoice_date    date,
      due_date        date,
      currency        text,
      subtotal        numeric(18,2),
      total_tax       numeric(18,2),
      invoice_total   numeric(18,2),
      created_at      timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS invoice_line_items (
      id              bigserial PRIMARY KEY,
      processed_hash  text NOT NULL REFERENCES invoices(processed_hash) ON DELETE CASCADE,
      line_no         int NOT NULL,
      description     text,
      quantity        numeric(18,4),
      unit_price      numeric(18,4),
      amount          numeric(18,2)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_invoice_line_items_processed_hash
      ON invoice_line_items(processed_hash)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_invoices_vendor_name ON invoices(vendor_name)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_invoices_invoice_date ON invoices(invoice_date)
    """,
)


def _embedding_dimensions() -> int:
    raw = (os.environ.get("AZURE_OPENAI_EMBEDDING_DIMENSIONS") or "1536").strip()
    dims = int(raw)
    if dims <= 0:
        raise ValueError("AZURE_OPENAI_EMBEDDING_DIMENSIONS must be positive")
    return dims


def _rag_schema_statements() -> tuple[str, ...]:
    dims = _embedding_dimensions()
    return (
        "CREATE EXTENSION IF NOT EXISTS vector",
        f"""
        CREATE TABLE IF NOT EXISTS doc_chunks (
          id            text PRIMARY KEY,
          raw_hash      text NOT NULL,
          source_file   text NOT NULL,
          page_number   int  NOT NULL,
          chunk_index   int  NOT NULL,
          content       text NOT NULL,
          embedding     vector({dims}) NOT NULL,
          title         text,
          doc_date      date,
          created_at    timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_doc_chunks_raw_hash
          ON doc_chunks(raw_hash)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_doc_chunks_source_page
          ON doc_chunks(source_file, page_number)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_doc_chunks_embedding_hnsw
          ON doc_chunks USING hnsw (embedding vector_cosine_ops)
        """,
    )


def _database_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _connect():
    psycopg, dict_row = _psycopg()
    return psycopg.connect(_database_url(), row_factory=dict_row)


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    statements = _INVOICE_SCHEMA_STATEMENTS + _rag_schema_statements()
    with _connect() as conn:
        with conn.transaction():
            for stmt in statements:
                conn.execute(stmt)
    _schema_ready = True
    logger.info(
        "Postgres schema ensured (invoices, invoice_line_items, doc_chunks vector(%s))",
        _embedding_dimensions(),
    )


def _field(fields: dict[str, Any], name: str) -> Any:
    node = fields.get(name)
    if not isinstance(node, dict):
        return None
    return node.get("value")


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        # address / unexpected object — ignore for scalar text columns
        return None
    text = str(value).strip()
    return text or None


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("amount")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # DI valueDate is typically YYYY-MM-DD; tolerate datetime prefix.
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _money(fields: dict[str, Any], name: str) -> tuple[Decimal | None, str | None]:
    value = _field(fields, name)
    if isinstance(value, dict):
        return _as_decimal(value.get("amount")), _as_text(value.get("currency"))
    return _as_decimal(value), None


def _line_scalar(row: dict[str, Any], name: str) -> Any:
    node = row.get(name)
    if not isinstance(node, dict):
        return None
    return node.get("value")


def map_invoice_row(
    *,
    processed_hash: str,
    raw_hash: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Map normalized invoice JSON → invoices row + line item rows. Unknown fields ignored."""
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    fields = fields or {}

    subtotal, _ = _money(fields, "SubTotal")
    total_tax, _ = _money(fields, "TotalTax")
    invoice_total, currency_from_total = _money(fields, "InvoiceTotal")
    amount_due, currency_from_due = _money(fields, "AmountDue")
    if invoice_total is None:
        invoice_total = amount_due

    currency = currency_from_total or currency_from_due

    invoice = {
        "processed_hash": processed_hash,
        "raw_hash": raw_hash,
        "vendor_name": _as_text(_field(fields, "VendorName")),
        "customer_name": _as_text(_field(fields, "CustomerName")),
        "invoice_id": _as_text(_field(fields, "InvoiceId")),
        "invoice_date": _as_date(_field(fields, "InvoiceDate")),
        "due_date": _as_date(_field(fields, "DueDate")),
        "currency": currency,
        "subtotal": subtotal,
        "total_tax": total_tax,
        "invoice_total": invoice_total,
    }

    items_node = fields.get("Items")
    rows_raw: list[Any] = []
    if isinstance(items_node, dict):
        value = items_node.get("value")
        if isinstance(value, list):
            rows_raw = value

    line_items: list[dict[str, Any]] = []
    for idx, row in enumerate(rows_raw, start=1):
        if not isinstance(row, dict):
            continue
        unit_price_val = _line_scalar(row, "UnitPrice")
        amount_val = _line_scalar(row, "Amount")
        qty_val = _line_scalar(row, "Quantity")
        unit_price, unit_currency = (
            (_as_decimal(unit_price_val.get("amount")), _as_text(unit_price_val.get("currency")))
            if isinstance(unit_price_val, dict)
            else (_as_decimal(unit_price_val), None)
        )
        amount, amount_currency = (
            (_as_decimal(amount_val.get("amount")), _as_text(amount_val.get("currency")))
            if isinstance(amount_val, dict)
            else (_as_decimal(amount_val), None)
        )
        if currency is None:
            currency = unit_currency or amount_currency
            invoice["currency"] = currency
        line_items.append(
            {
                "processed_hash": processed_hash,
                "line_no": idx,
                "description": _as_text(_line_scalar(row, "Description")),
                "quantity": _as_decimal(qty_val),
                "unit_price": unit_price,
                "amount": amount,
            }
        )

    return invoice, line_items


def upsert_invoice(
    *,
    processed_hash: str,
    raw_hash: str,
    payload: dict[str, Any],
) -> None:
    """Insert/update invoice columns + replace line items. PK = processed_hash."""
    ensure_schema()
    invoice, line_items = map_invoice_row(
        processed_hash=processed_hash,
        raw_hash=raw_hash,
        payload=payload,
    )
    with _connect() as conn:
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO invoices (
                  processed_hash, raw_hash, vendor_name, customer_name, invoice_id,
                  invoice_date, due_date, currency, subtotal, total_tax, invoice_total
                ) VALUES (
                  %(processed_hash)s, %(raw_hash)s, %(vendor_name)s, %(customer_name)s, %(invoice_id)s,
                  %(invoice_date)s, %(due_date)s, %(currency)s, %(subtotal)s, %(total_tax)s, %(invoice_total)s
                )
                ON CONFLICT (processed_hash) DO UPDATE SET
                  raw_hash = EXCLUDED.raw_hash,
                  vendor_name = EXCLUDED.vendor_name,
                  customer_name = EXCLUDED.customer_name,
                  invoice_id = EXCLUDED.invoice_id,
                  invoice_date = EXCLUDED.invoice_date,
                  due_date = EXCLUDED.due_date,
                  currency = EXCLUDED.currency,
                  subtotal = EXCLUDED.subtotal,
                  total_tax = EXCLUDED.total_tax,
                  invoice_total = EXCLUDED.invoice_total
                """,
                invoice,
            )
            conn.execute(
                "DELETE FROM invoice_line_items WHERE processed_hash = %s",
                (processed_hash,),
            )
            for item in line_items:
                conn.execute(
                    """
                    INSERT INTO invoice_line_items (
                      processed_hash, line_no, description, quantity, unit_price, amount
                    ) VALUES (
                      %(processed_hash)s, %(line_no)s, %(description)s,
                      %(quantity)s, %(unit_price)s, %(amount)s
                    )
                    """,
                    item,
                )
    logger.info(
        "Upserted invoice processed_hash=%s lines=%d vendor=%s total=%s",
        processed_hash[:12],
        len(line_items),
        invoice.get("vendor_name"),
        invoice.get("invoice_total"),
    )


def delete_invoice_by_processed_hash(processed_hash: str) -> bool:
    """Delete invoice row (line items CASCADE). Returns True if a row was deleted."""
    ensure_schema()
    with _connect() as conn:
        with conn.transaction():
            cur = conn.execute(
                "DELETE FROM invoices WHERE processed_hash = %s",
                (processed_hash,),
            )
            deleted = cur.rowcount > 0
    if deleted:
        logger.info("Deleted invoice processed_hash=%s", processed_hash[:12])
    else:
        logger.info("No invoice row for processed_hash=%s", processed_hash[:12])
    return deleted


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in values) + "]"


def replace_doc_chunks(*, raw_hash: str, rows: list[dict[str, Any]]) -> None:
    """Replace all chunks for a document (delete by raw_hash, then insert)."""
    ensure_schema()
    with _connect() as conn:
        with conn.transaction():
            conn.execute("DELETE FROM doc_chunks WHERE raw_hash = %s", (raw_hash,))
            for row in rows:
                emb = row.get("embedding") or []
                conn.execute(
                    """
                    INSERT INTO doc_chunks (
                      id, raw_hash, source_file, page_number, chunk_index,
                      content, embedding, title, doc_date
                    ) VALUES (
                      %s, %s, %s, %s, %s,
                      %s, %s::vector, %s, %s
                    )
                    """,
                    (
                        row["id"],
                        row["raw_hash"],
                        row["source_file"],
                        int(row["page_number"]),
                        int(row["chunk_index"]),
                        row["content"],
                        _vector_literal(list(emb)),
                        row.get("title"),
                        row.get("doc_date"),
                    ),
                )
    logger.info("Replaced doc_chunks raw_hash=%s count=%d", raw_hash[:12], len(rows))


def delete_doc_chunks_by_raw_hash(raw_hash: str) -> int:
    """Delete all chunks for a document. Returns deleted row count."""
    ensure_schema()
    with _connect() as conn:
        with conn.transaction():
            cur = conn.execute(
                "DELETE FROM doc_chunks WHERE raw_hash = %s",
                (raw_hash,),
            )
            deleted = cur.rowcount
    logger.info("Deleted doc_chunks raw_hash=%s count=%d", raw_hash[:12], deleted)
    return deleted
