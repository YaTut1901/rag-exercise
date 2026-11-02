"""Readonly SQL tool over invoice tables (model-generated SQL + optional chart)."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

from db import run_readonly_sql

logger = logging.getLogger(__name__)

_CHART_TYPES = frozenset({"bar", "line", "pie"})


def _normalize_chart(chart: str | None) -> str | None:
    raw = (chart or "none").strip().lower()
    if raw in ("", "none", "false", "0", "no"):
        return None
    if raw not in _CHART_TYPES:
        raise ValueError(
            f"chart must be one of: none, {', '.join(sorted(_CHART_TYPES))}; got {chart!r}"
        )
    return raw


def build_chart_payload(
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
    chart: str,
    title: str = "",
) -> dict[str, Any]:
    """Build UI chart spec from SQL result (col0 = labels, col1 = numeric values)."""
    if len(columns) < 2:
        raise ValueError(
            "Chart requires at least 2 SELECT columns: first=labels, second=numeric values"
        )
    if not rows:
        raise ValueError("No rows to chart; adjust the SQL")

    label_col, value_col = columns[0], columns[1]
    labels: list[str] = []
    values: list[float] = []
    for row in rows:
        lab = row.get(label_col)
        labels.append("" if lab is None else str(lab))
        raw = row.get(value_col)
        try:
            values.append(float(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Second column {value_col!r} must be numeric for charting; "
                f"got {raw!r}. Select labels then a number."
            ) from exc

    return {
        "type": chart,
        "title": (title or "").strip() or f"{value_col} by {label_col}",
        "label_column": label_col,
        "value_column": value_col,
        "labels": labels,
        "values": values,
    }


@tool
def invoice_sql(sql: str, chart: str = "none", title: str = "") -> str:
    """Run a read-only SQL query against invoice analytics tables and return JSON.

    Use for invoice statistics and aggregations (totals by vendor, counts, sums,
    averages, date ranges, line-item rollups). You generate the SQL; this tool
    only executes it.

    Allowed tables/columns:
      invoices(
        processed_hash, raw_hash, vendor_name, customer_name, invoice_id,
        invoice_date, due_date, currency, subtotal, total_tax (VAT), invoice_total,
        created_at
      )
      invoice_line_items(
        id, processed_hash, line_no, description, quantity, unit_price, amount
      )
    Join line items with: invoice_line_items.processed_hash = invoices.processed_hash

    Charts: set chart to bar, line, or pie (default none). SQL must return at
    least two columns — first = category labels, second = numeric values.
    The UI renders the chart; still summarize the numbers in your reply.
    If the user does not explicitly suggest the form, choose on your own

    Rules: one SELECT or WITH…SELECT only; no writes/DDL. Prefer LIMIT.
    If the tool returns ok=false, read the error, fix the SQL/chart, and call again.

    Args:
        sql: A single PostgreSQL SELECT (or WITH … SELECT) query.
        chart: none | bar | line | pie. Use bar/line/pie when the user asks for a chart/graph.
        title: Optional chart title.
    """
    try:
        result = run_readonly_sql(sql)
        chart_kind = _normalize_chart(chart)
        if chart_kind:
            result["chart"] = build_chart_payload(
                columns=list(result.get("columns") or []),
                rows=list(result.get("rows") or []),
                chart=chart_kind,
                title=title,
            )
        logger.info(
            "invoice_sql ok rows=%s chart=%s sql=%r",
            result.get("row_count"),
            chart_kind or "none",
            (sql or "")[:120],
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — return to model for retry
        logger.warning("invoice_sql error: %s; sql=%r", exc, (sql or "")[:200])
        return json.dumps(
            {
                "ok": False,
                "error": str(exc),
                "hint": "Fix the SQL/chart args and call invoice_sql again.",
            },
            ensure_ascii=False,
        )
