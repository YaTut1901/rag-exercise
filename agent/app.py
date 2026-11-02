"""Streamlit UI — chat agent + pipeline entry points (upload / delete result)."""

from __future__ import annotations

import streamlit as st

from charts import render_chart
from config import api_version, chat_deployment, openai_endpoint
from graph import build_agent, run_agent
from storage import (
    default_uploader_email,
    delete_result_json,
    list_result_jsons,
    upload_pdf,
)


@st.cache_resource(show_spinner=False)
def _cached_agent():
    return build_agent()


st.set_page_config(page_title="RAG Lab", page_icon="💬", layout="centered")
st.title("RAG Lab")

tab_chat, tab_pipeline = st.tabs(["Chat", "Pipeline"])

with st.sidebar:
    st.subheader("Config")
    try:
        st.code(
            f"endpoint: {openai_endpoint()}\n"
            f"chat: {chat_deployment()}\n"
            f"api: {api_version()}",
            language="text",
        )
    except RuntimeError as exc:
        st.error(str(exc))
    if st.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()
    if st.button("Rebuild agent cache"):
        _cached_agent.clear()
        st.rerun()

with tab_chat:
    st.caption("Tools: `company_rag`, `invoice_sql`")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            for chart in msg.get("charts") or []:
                render_chart(chart)
            if msg.get("tools"):
                st.caption("tools: " + ", ".join(msg["tools"]))

    prompt = st.chat_input("Запитання…")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[:-1]
        ]
        with st.chat_message("assistant"):
            try:
                with st.spinner("Thinking / retrieving…"):
                    answer, tools, charts = run_agent(
                        history, prompt, agent=_cached_agent()
                    )
                st.markdown(answer or "_(порожня відповідь)_")
                for chart in charts:
                    render_chart(chart)
                if tools:
                    st.caption("tools: " + ", ".join(tools))
            except Exception as exc:  # noqa: BLE001 — show in UI
                st.error(f"Chat failed: {exc}")
                st.stop()
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": answer or "",
                "tools": tools,
                "charts": charts,
            }
        )

with tab_pipeline:
    st.caption(
        "User entry points from the architecture diagram: "
        "upload PDF → `invoices-in`, delete result JSON → `delete_result`."
    )

    st.subheader("Upload PDFs")
    if "uploader_email" not in st.session_state:
        st.session_state.uploader_email = default_uploader_email()

    email = st.text_input(
        "uploaderEmail",
        value=st.session_state.uploader_email,
        help="Written as blob metadata; notify emails go here.",
    )
    st.session_state.uploader_email = email

    uploaded_files = st.file_uploader(
        "PDF files", type=["pdf"], accept_multiple_files=True
    )
    if st.button("Upload to invoices-in", disabled=not uploaded_files):
        ok_paths: list[str] = []
        errors: list[str] = []
        for f in uploaded_files:
            try:
                ok_paths.append(
                    upload_pdf(
                        blob_name=f.name,
                        data=f.getvalue(),
                        uploader_email=email,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{f.name}: {exc}")
        if ok_paths:
            st.success(
                f"Uploaded {len(ok_paths)} file(s). Pipeline: Event Grid → q-ingress → …\n\n"
                + "\n".join(f"- `{p}`" for p in ok_paths)
            )
        for err in errors:
            st.error(f"Upload failed: {err}")

    st.divider()
    st.subheader("Delete result JSON")
    st.caption(
        "Deletes `{rawHash}.json` from out containers. "
        "Event Grid → q-delete-result clears docHashes / Postgres / doc_chunks."
    )

    refresh = st.button("Refresh list")
    if refresh or "result_blobs" not in st.session_state:
        try:
            with st.spinner("Listing result JSON…"):
                st.session_state.result_blobs = list_result_jsons()
                st.session_state.result_list_error = None
        except Exception as exc:  # noqa: BLE001
            st.session_state.result_blobs = []
            st.session_state.result_list_error = str(exc)

    if st.session_state.get("result_list_error"):
        st.error(st.session_state.result_list_error)
    blobs = st.session_state.get("result_blobs") or []
    if not blobs:
        st.info("No result JSON found in out containers.")
    else:
        label_to_blob = {
            f"{b.container}/{b.name}"
            + (f"  ({b.last_modified:%Y-%m-%d %H:%M} UTC)" if b.last_modified else ""): b
            for b in blobs
        }
        choices = st.multiselect("Result JSON", list(label_to_blob.keys()))
        if st.button(
            "Delete selected JSON", type="primary", disabled=not choices
        ):
            deleted_ok: list[str] = []
            delete_errors: list[str] = []
            removed = set()
            for label in choices:
                selected = label_to_blob[label]
                try:
                    deleted_ok.append(
                        delete_result_json(
                            container=selected.container, name=selected.name
                        )
                    )
                    removed.add((selected.container, selected.name))
                except Exception as exc:  # noqa: BLE001
                    delete_errors.append(f"{selected.container}/{selected.name}: {exc}")
            if deleted_ok:
                st.success(
                    f"Deleted {len(deleted_ok)} file(s). Waiting for delete_result…\n\n"
                    + "\n".join(f"- `{p}`" for p in deleted_ok)
                )
                st.session_state.result_blobs = [
                    b
                    for b in blobs
                    if (b.container, b.name) not in removed
                ]
            for err in delete_errors:
                st.error(f"Delete failed: {err}")
