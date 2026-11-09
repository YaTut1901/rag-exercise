"""Render invoice_sql chart payloads in Streamlit."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
import streamlit as st


def render_chart(chart: dict[str, Any]) -> None:
    labels = list(chart.get("labels") or [])
    values = list(chart.get("values") or [])
    title = chart.get("title") or ""
    kind = (chart.get("type") or "bar").lower()

    if kind == "pie":
        fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0)])
    elif kind == "line":
        fig = go.Figure(data=[go.Scatter(x=labels, y=values, mode="lines+markers")])
    else:
        fig = go.Figure(data=[go.Bar(x=labels, y=values)])

    fig.update_layout(
        title=title or None,
        margin=dict(l=24, r=24, t=48, b=24),
        height=360,
    )
    if kind != "pie":
        fig.update_layout(
            xaxis_title=chart.get("label_column") or "",
            yaxis_title=chart.get("value_column") or "",
        )
    st.plotly_chart(fig, use_container_width=True)
