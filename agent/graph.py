"""LangGraph ReAct agent with RAG tool."""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent

from azure_auth import token_provider
from config import api_version, chat_deployment, openai_endpoint, system_prompt
from tools.invoice_sql import invoice_sql
from tools.rag import company_rag


def _chat_model() -> AzureChatOpenAI:
    api_key = (os.environ.get("AZURE_OPENAI_API_KEY") or "").strip()
    kwargs: dict[str, Any] = {
        "azure_endpoint": openai_endpoint(),
        "azure_deployment": chat_deployment(),
        "openai_api_version": api_version(),
        "temperature": 0.2,
    }
    if api_key:
        kwargs["api_key"] = api_key
    else:
        kwargs["azure_ad_token_provider"] = token_provider()
    return AzureChatOpenAI(**kwargs)


def build_agent():
    return create_react_agent(
        model=_chat_model(),
        tools=[company_rag, invoice_sql],
        prompt=system_prompt(),
    )


def history_to_messages(history: list[dict[str, str]]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for turn in history:
        role = turn.get("role")
        content = turn.get("content") or ""
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
    return out


def _charts_from_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        raw = msg.content
        if not isinstance(raw, str):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not payload.get("ok"):
            continue
        chart = payload.get("chart")
        if isinstance(chart, dict) and chart.get("type") and chart.get("labels") is not None:
            charts.append(chart)
    return charts


def run_agent(
    history: list[dict[str, str]],
    user_text: str,
    *,
    agent=None,
) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Run one user turn. Returns (assistant_text, tool_names_used, charts)."""
    graph = agent or build_agent()
    messages = history_to_messages(history) + [HumanMessage(content=user_text)]
    result = graph.invoke({"messages": messages})
    result_messages: list[BaseMessage] = result.get("messages") or []

    tool_names: list[str] = []
    for msg in result_messages:
        for call in getattr(msg, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                tool_names.append(str(name))

    answer = ""
    for msg in reversed(result_messages):
        if isinstance(msg, AIMessage) and msg.content and not (getattr(msg, "tool_calls", None) or []):
            content = msg.content
            if isinstance(content, list):
                answer = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            else:
                answer = str(content)
            break
    return answer, tool_names, _charts_from_messages(result_messages)
