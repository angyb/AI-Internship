"""Minimal Streamlit UI for the Week 2 RAG API — calls /ingest and /ask only.

Run:
  cd ai-engineering-bootcamp-v2/week-2/rag-vector-databases
  source .venv/bin/activate
  pip install streamlit httpx python-dotenv
  export RAG_API_URL=https://your-app.onrender.com   # optional; override in sidebar
  streamlit run demo_page.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx
import streamlit as st
from dotenv import load_dotenv

from eval_format import (
    agent_check_comparison_rows,
    agent_check_summary_rows,
    agent_trace_check_rows,
    averages_rows,
    per_question_score_rows,
    questions_and_answers_rows,
    retrieval_config_rows,
)

load_dotenv(Path(__file__).resolve().parent / ".env")

DEFAULT_API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000")
WORKDIR_CMD = "ai-engineering-bootcamp-v2/week-2/rag-vector-databases"
CITATION_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
LEGACY_CITATION_RE = re.compile(r"\[document_id:\s*([^\]]+)\]", re.IGNORECASE)

SAMPLE_INGEST = {
    "document_id": "demo-accessibility",
    "text": (
        "Zearn digital lessons include closed captioning on all student videos, "
        "text-to-speech for problem prompts, an on-screen keypad for tablet users, "
        "zoom up to 200% without losing content, and the ability to rewind and rewatch "
        "any part of a lesson."
    ),
}

SAMPLE_QUESTION = (
    "Give me a succinct list of accessibility features in Zearn digital lessons — "
    "feature names only, no descriptions."
)


def api_url() -> str:
    return st.session_state.get("api_url", DEFAULT_API_URL).rstrip("/")


def call_json(
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    timeout: float = 120.0,
) -> tuple[int, dict | str]:
    url = f"{api_url()}{path}"
    headers: dict[str, str] = {}
    code = str(st.session_state.get("override_code") or "").strip() or os.getenv(
        "AGENT_OVERRIDE_CODE", ""
    ).strip()
    if code:
        headers["X-Override-Code"] = code
    try:
        with httpx.Client(timeout=timeout) as client:
            if method == "GET":
                response = client.get(url, headers=headers or None)
            else:
                response = client.post(url, json=payload, headers=headers or None)
        try:
            return response.status_code, response.json()
        except json.JSONDecodeError:
            return response.status_code, response.text
    except httpx.ConnectError:
        return 0, {"error": f"Cannot reach {url}. Check the API URL and that the service is running."}
    except httpx.HTTPError as exc:
        return 0, {"error": str(exc)}


def extract_citations(answer_text: str) -> list[tuple[str, str]]:
    """Return (label, url) pairs — markdown links or legacy document_id citations."""
    links = CITATION_LINK_RE.findall(answer_text)
    if links:
        return [(title.strip(), url.strip()) for title, url in links]
    return [(doc_id.strip(), "") for doc_id in LEGACY_CITATION_RE.findall(answer_text)]


def render_api_error(status: int, data: dict | str) -> None:
    st.error(f"Request failed (HTTP {status})")
    if isinstance(data, dict) and "detail" in data:
        st.code(json.dumps(data["detail"], indent=2), language="json")
    else:
        st.code(str(data), language="json")


st.set_page_config(page_title="Week 2 RAG Demo", layout="wide")
st.title("Week 2 — RAG API Demo")
st.caption("Streamlit calls your FastAPI service only. No RAG logic runs in this UI.")

if "api_url" not in st.session_state:
    st.session_state.api_url = DEFAULT_API_URL
if "override_code" not in st.session_state:
    st.session_state.override_code = os.getenv("AGENT_OVERRIDE_CODE", "")

st.sidebar.header("API connection")
st.session_state.api_url = st.sidebar.text_input(
    "API base URL",
    value=st.session_state.api_url,
    help="Set RAG_API_URL in .env or paste your Render URL here.",
)
st.sidebar.text_input(
    "Unlock / operator code",
    type="password",
    key="override_code",
    help="Sent as X-Override-Code. Required on Render for /ingest, /retrieve, and /eval.",
)

if st.sidebar.button("Check /health"):
    status, data = call_json("GET", "/health")
    if status == 200:
        st.sidebar.success(f"OK — {data}")
    else:
        st.sidebar.error(f"HTTP {status}: {data}")

st.sidebar.markdown("### Run this page")
st.sidebar.code(
    f"cd {WORKDIR_CMD}\n"
    "source .venv/bin/activate\n"
    "pip install streamlit httpx python-dotenv\n"
    "export RAG_API_URL=https://your-app.onrender.com\n"
    "streamlit run demo_page.py",
    language="bash",
)

ingest_tab, ask_tab, eval_tab, agent_checks_tab = st.tabs(
    ["Ingest", "Ask", "Eval", "Agent Checks"]
)

with ingest_tab:
    st.subheader("POST /ingest — paste a document")
    st.markdown(
        "Sends `document_id` + `text` to the API. The server chunks, embeds, and upserts "
        "to Pinecone (replacing any prior vectors for the same `document_id`)."
    )

    col1, col2 = st.columns([1, 2])
    with col1:
        document_id = st.text_input("document_id", value=SAMPLE_INGEST["document_id"])
    with col2:
        st.caption("Use a stable id — it appears in retrieval citations.")

    text = st.text_area("Document text", value=SAMPLE_INGEST["text"], height=180)

    if st.button("Ingest document", type="primary"):
        if not document_id.strip() or not text.strip():
            st.warning("Both document_id and text are required.")
        else:
            payload = {"document_id": document_id.strip(), "text": text}
            with st.spinner("Calling /ingest..."):
                status, data = call_json("POST", "/ingest", payload)

            if status == 200 and isinstance(data, dict):
                st.success(
                    f"Ingested **{data.get('chunks_indexed', 0)}** chunks "
                    f"for `{data.get('document_id', document_id)}`"
                )
                st.json(data)
            else:
                render_api_error(status, data)

with ask_tab:
    st.subheader("POST /ask — question with citations")
    st.caption(
        "General queries search the full ingested corpus. "
        "Set `EXCLUDE_DOCUMENT_IDS` on the API to omit specific document_ids."
    )
    question = st.text_area("Question", value=SAMPLE_QUESTION, height=100)

    if st.button("Ask", type="primary"):
        if not question.strip():
            st.warning("Enter a question first.")
        else:
            payload = {"question": question.strip()}
            with st.spinner("Calling /ask..."):
                status, data = call_json("POST", "/ask", payload)

            if status != 200 or not isinstance(data, dict):
                render_api_error(status, data)
            else:
                answer_obj = data.get("answer", {})
                answer_text = answer_obj.get("answer", "")
                sources_needed = bool(answer_obj.get("sources_needed"))
                confidence = answer_obj.get("confidence")
                inline_citations = extract_citations(answer_text)
                chunk_ids = data.get("chunk_ids") or []
                sources = data.get("sources") or []

                if sources_needed:
                    st.error("Refusal — context insufficient (`sources_needed: true`)")
                else:
                    st.success("Answer grounded in retrieved context")

                st.markdown("### Answer")
                st.markdown(answer_text)

                st.markdown("### Citations")
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("Confidence", f"{confidence:.2f}" if confidence is not None else "—")
                with c2:
                    st.metric("Chunks retrieved", len(chunk_ids))
                with c3:
                    st.metric("Tokens", data.get("tokens_used", "—"))

                if inline_citations:
                    st.markdown("**Citations in answer**")
                    seen: set[tuple[str, str]] = set()
                    for label, url in inline_citations:
                        key = (label, url)
                        if key in seen:
                            continue
                        seen.add(key)
                        if url:
                            st.markdown(f"- [{label}]({url})")
                        else:
                            st.markdown(f"- `{label}`")

                if chunk_ids:
                    st.markdown("**chunk_ids returned by API**")
                    for chunk_id in chunk_ids:
                        st.markdown(f"- `{chunk_id}`")

                if sources:
                    st.markdown("**sources**")
                    for source in sources:
                        st.markdown(f"- {source}")

                with st.expander("Full JSON response"):
                    st.json(data)

with eval_tab:
    st.subheader("POST /eval — golden-set evaluation")
    st.markdown(
        "Runs all questions in `golden_set.json` against the ingested Zearn corpus: "
        "retrieval, answer generation, and RAGAS scoring (faithfulness + answer_correctness). "
        "Ensure the full corpus is indexed (`POST /ingest`) before running eval. "
        "When pointed at Render, the eval runs on the server — no local terminal needed."
    )

    if st.button("Run golden-set eval", type="primary"):
        with st.spinner("Running eval (retrieval + generation + RAGAS — may take 2–3 minutes)..."):
            status, data = call_json("POST", "/eval", {}, timeout=600.0)

        if status != 200 or not isinstance(data, dict):
            render_api_error(status, data)
        else:
            averages = data.get("averages", {})
            faith = averages.get("faithfulness")
            correctness = averages.get("answer_correctness")

            st.success(f"Eval complete — {data.get('golden_set', 'golden_set.json')}")

            config = data.get("config")
            if config:
                st.markdown("**Retrieval config**")
                st.dataframe(retrieval_config_rows(config), use_container_width=True, hide_index=True)

            if faith is None or correctness is None:
                st.warning(
                    "Some RAGAS scores came back empty (common on Render under load). "
                    "Re-run eval once — scores usually fill in on retry."
                )

            if averages:
                st.markdown("**Averages**")
                st.dataframe(averages_rows(averages), use_container_width=True, hide_index=True)

            questions = data.get("questions", [])
            if questions:
                st.markdown("**Per-question scores**")
                st.dataframe(
                    per_question_score_rows(questions),
                    use_container_width=True,
                    hide_index=True,
                )

            if questions:
                st.markdown("**Questions and answers**")
                st.dataframe(
                    questions_and_answers_rows(questions),
                    use_container_width=True,
                    hide_index=True,
                )

            with st.expander("Full JSON response"):
                st.json(data)

with agent_checks_tab:
    st.subheader("POST /eval-agent — TRACE deterministic checks")
    st.markdown(
        "Scores committed agent traces in `traces/zearn_agent_traces.jsonl` with "
        "binary pass/fail checks (used_tool, citation_present, fallback_banner, "
        "outcome_appropriate, length_budget). Includes before/after snapshots from "
        "`traces/eval_before.json` and `traces/eval_after.json` when present."
    )
    regenerate = st.checkbox(
        "Regenerate traces first (slow — re-runs the ADK agent on all questions)",
        value=False,
    )

    if st.button("Run agent checks", type="primary"):
        payload = {"regenerate": regenerate}
        with st.spinner("Running agent checks…"):
            status, data = call_json("POST", "/eval-agent", payload, timeout=600.0)

        if status != 200 or not isinstance(data, dict):
            render_api_error(status, data)
        else:
            summary = data.get("summary") or {}
            st.success(
                f"Agent checks complete — {summary.get('all_checks_passed', 0)}/"
                f"{summary.get('trace_count', 0)} traces passed all checks"
            )

            if summary:
                st.markdown("**Check pass rates**")
                st.dataframe(
                    agent_check_summary_rows(summary),
                    use_container_width=True,
                    hide_index=True,
                )

            before = data.get("before")
            after = data.get("after")
            comparison = agent_check_comparison_rows(before, after)
            if comparison:
                st.markdown("**Before / after fix (citation_present target)**")
                st.dataframe(comparison, use_container_width=True, hide_index=True)

            rows = data.get("rows") or []
            if rows:
                st.markdown("**Per-trace results**")
                st.dataframe(
                    agent_trace_check_rows(rows),
                    use_container_width=True,
                    hide_index=True,
                )

            with st.expander("Full JSON response"):
                st.json(data)
