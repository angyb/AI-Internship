"""
Zearn Support Agent — Streamlit demo with Think → Act → Observe step logs.

Run:
    streamlit run zearn_streamlit_app.py
"""

import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from zearn_support_agent import RAG_API_URL, run_zearn_agent

st.set_page_config(page_title="Zearn Support Agent", layout="wide")
st.markdown("<style>.block-container{padding-top:1.5rem;}</style>", unsafe_allow_html=True)


def check_rag_health(base_url: str) -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{base_url.rstrip('/')}/health")
            if response.status_code == 200:
                return True, response.text
            return False, f"HTTP {response.status_code}"
    except httpx.RequestError as exc:
        return False, str(exc)


def render_steps(steps: list[dict]) -> None:
    if not steps:
        st.info("No steps recorded.")
        return

    for i, step in enumerate(steps, start=1):
        phase = step.get("phase", "")
        if phase == "Think":
            with st.container(border=True):
                st.markdown(f"**Step {i} — Think** (`{step.get('author', '')}`)")
                st.markdown(step.get("text", ""))
        elif phase == "Act":
            args = step.get("args", {})
            args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            st.warning(f"**Step {i} — Act:** `{step.get('tool')}`({args_str})")
        elif phase == "Observe":
            st.success(f"**Step {i} — Observe:** result from `{step.get('tool')}`")
            if step.get("result"):
                st.code(step["result"], language="json")


# --- Sidebar ---

with st.sidebar:
    st.title("Zearn Support Agent")
    st.caption("Week 3 ADK agent with search_docs tool")

    api_key = os.getenv("GOOGLE_API_KEY")
    if api_key:
        st.success("GOOGLE_API_KEY set")
    else:
        st.error("GOOGLE_API_KEY missing — add to .env")

    st.markdown(f"**RAG API:** `{RAG_API_URL}`")
    healthy, detail = check_rag_health(RAG_API_URL)
    if healthy:
        st.success("RAG API reachable")
    else:
        st.error(f"RAG API unreachable: {detail}")
        st.caption("Start: `uvicorn main:app --host 127.0.0.1 --port 8000` in week-2/rag-vector-databases")

# --- Main ---

st.header("Zearn Teacher Support Agent")
st.markdown(
    "Ask a Zearn support question. The agent searches the knowledge base via "
    "**search_docs** (Week 2 hybrid retrieval) and answers from retrieved chunks."
)

if not api_key:
    st.stop()

with st.form("question_form", clear_on_submit=False):
    col1, col2 = st.columns([3, 1])
    with col1:
        question = st.text_input(
            "Your question",
            value="What causes a Tower Alert and what is its purpose?",
            label_visibility="collapsed",
            placeholder="Ask a Zearn support question...",
        )
    with col2:
        run_clicked = st.form_submit_button("Run agent", type="primary", use_container_width=True)

if run_clicked and question.strip():
    with st.spinner("Agent running..."):
        try:
            answer, steps = run_zearn_agent(question.strip())
        except Exception as exc:
            st.error(f"Agent error: {exc}")
            st.stop()

    st.markdown("---")
    st.subheader("Think → Act → Observe")
    render_steps(steps)

    st.markdown("---")
    st.subheader("Final answer")
    st.markdown(answer)

    with st.expander("Raw step data"):
        st.json(steps)
