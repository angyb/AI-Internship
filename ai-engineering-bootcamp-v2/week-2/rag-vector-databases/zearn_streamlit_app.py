"""
Zearn Support Agent — Streamlit demo with Think → Act → Observe step logs.

Run locally (in-process agent; start uvicorn in this folder first for /health):
    streamlit run zearn_streamlit_app.py

Run against remote API (Render UI service):
    AGENT_API_URL=https://your-rag-api.onrender.com streamlit run zearn_streamlit_app.py
"""

import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

AGENT_API_URL = os.getenv("AGENT_API_URL", "").rstrip("/")
REMOTE_MODE = bool(AGENT_API_URL)
HEALTH_TIMEOUT = float(os.getenv("API_HEALTH_TIMEOUT", "60"))
AGENT_TIMEOUT = float(os.getenv("API_AGENT_TIMEOUT", "120"))
LOCAL_API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000").rstrip("/")

if not REMOTE_MODE:
    from zearn_support_agent import FALLBACK_PREFIX, REFUSAL_MESSAGE, run_zearn_agent

    RAG_API_URL = LOCAL_API_URL
else:
    RAG_API_URL = AGENT_API_URL
    REFUSAL_MESSAGE = (
        "I couldn't find that in the Zearn documentation corpus. "
        "Try rephrasing your question, or contact Zearn support for help."
    )
    FALLBACK_PREFIX = (
        "This wasn't found in Zearn documentation; sourced from the web."
    )

st.set_page_config(page_title="Zearn Support Agent", layout="wide")
st.markdown("<style>.block-container{padding-top:1.5rem;}</style>", unsafe_allow_html=True)


def check_api_health(base_url: str, timeout: float = HEALTH_TIMEOUT) -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{base_url.rstrip('/')}/health")
            if response.status_code == 200:
                return True, response.text
            return False, f"HTTP {response.status_code}"
    except httpx.RequestError as exc:
        return False, str(exc)


def run_agent_remote(question: str) -> tuple[str, list[dict]]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("AGENT_API_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    with httpx.Client(timeout=AGENT_TIMEOUT) as client:
        response = client.post(
            f"{AGENT_API_URL}/agent",
            json={"question": question},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
    return data["answer"], data.get("steps", [])


def used_web_fallback(steps: list[dict]) -> bool:
    for step in steps:
        tool = step.get("tool") or ""
        if tool in ("google_search_agent", "google_search"):
            return True
    return False


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
            args = step.get("args") or {}
            args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            st.warning(f"**Step {i} — Act:** `{step.get('tool')}`({args_str})")
        elif phase == "Observe":
            st.success(f"**Step {i} — Observe:** result from `{step.get('tool')}`")
            if step.get("result"):
                st.code(step["result"], language="json")


# --- Sidebar ---

with st.sidebar:
    st.title("Zearn Support Agent")
    st.caption("ADK agent with search_zearn_doc + google_search_agent fallback")

    if REMOTE_MODE:
        st.info(f"Remote mode — `{AGENT_API_URL}`")
    else:
        api_key = os.getenv("GOOGLE_API_KEY")
        if api_key:
            st.success("GOOGLE_API_KEY set")
        else:
            st.error("GOOGLE_API_KEY missing — add to .env")

    st.markdown(f"**API:** `{RAG_API_URL}`")
    if REMOTE_MODE:
        with st.spinner(
            "Checking API… first visit may take up to a minute while the service wakes up."
        ):
            healthy, detail = check_api_health(RAG_API_URL)
    else:
        healthy, detail = check_api_health(RAG_API_URL)
    if healthy:
        st.success("API reachable")
    else:
        st.error(f"API unreachable: {detail}")
        if REMOTE_MODE:
            st.info(
                "The API may still be starting on Render. Wait a moment and **refresh** "
                "this page, or open the `/health` URL in a new tab to wake it up."
            )
        else:
            st.caption(
                "Start: `uvicorn main:app --host 127.0.0.1 --port 8000` in this folder"
            )

# --- Main ---

st.header("Zearn Support Agent")
st.markdown(
    "Ask a Zearn support question. The agent searches the knowledge base via "
    "**search_zearn_doc** (hybrid retrieval) and falls back to **google_search_agent** "
    "when Zearn docs do not answer."
)

if not REMOTE_MODE and not os.getenv("GOOGLE_API_KEY"):
    st.stop()

with st.form("question_form", clear_on_submit=False):
    col1, col2 = st.columns([3, 1])
    with col1:
        question = st.text_input(
            "Your question",
            label_visibility="collapsed",
            placeholder="Ask a Zearn support question...",
        )
    with col2:
        run_clicked = st.form_submit_button("Run agent", type="primary", use_container_width=True)

if run_clicked and question.strip():
    spinner_msg = (
        "Running agent… first request may take up to a minute while the API wakes up."
        if REMOTE_MODE
        else "Agent running..."
    )
    with st.spinner(spinner_msg):
        try:
            if REMOTE_MODE:
                answer, steps = run_agent_remote(question.strip())
            else:
                answer, steps = run_zearn_agent(question.strip())
        except httpx.HTTPStatusError as exc:
            st.error(f"API error {exc.response.status_code}: {exc.response.text[:500]}")
            st.stop()
        except Exception as exc:
            st.error(f"Agent error: {exc}")
            st.stop()

    st.markdown("---")
    st.subheader("Think → Act → Observe")
    render_steps(steps)

    st.markdown("---")
    st.subheader("Final answer")
    is_web_fallback = FALLBACK_PREFIX in answer or used_web_fallback(steps)
    is_refusal = (
        not is_web_fallback
        and (
            not answer.strip()
            or answer.strip() == REFUSAL_MESSAGE
            or "couldn't find that in the zearn documentation corpus" in answer.lower()
        )
    )
    if is_web_fallback:
        st.info("Not found in Zearn docs — sourced from the web")
    elif is_refusal:
        st.warning("Not found in corpus")
    st.markdown(answer.strip() if answer.strip() else REFUSAL_MESSAGE)

    with st.expander("Raw step data"):
        st.json(steps)
