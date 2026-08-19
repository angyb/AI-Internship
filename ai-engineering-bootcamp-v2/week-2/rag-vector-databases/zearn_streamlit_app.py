"""
Zearn Support Agent — Streamlit demo with Think → Act → Observe step logs.

Run locally (in-process agent; start uvicorn in this folder first for /health):
    streamlit run zearn_streamlit_app.py

Run against remote API (Render UI service):
    AGENT_API_URL=https://your-rag-api.onrender.com streamlit run zearn_streamlit_app.py
"""

import os
import uuid

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Render UI service uses requirements-streamlit.txt (no google-adk). Always call the API.
DEFAULT_PRODUCTION_AGENT_API_URL = "https://ai-internship-i3lw.onrender.com"

AGENT_API_URL = os.getenv("AGENT_API_URL", "").strip().rstrip("/")
if not AGENT_API_URL and os.getenv("RENDER"):
    AGENT_API_URL = DEFAULT_PRODUCTION_AGENT_API_URL

REMOTE_MODE = bool(AGENT_API_URL)
HEALTH_TIMEOUT = float(os.getenv("API_HEALTH_TIMEOUT", "60"))
AGENT_TIMEOUT = float(os.getenv("API_AGENT_TIMEOUT", "120"))
LOCAL_API_URL = os.getenv("RAG_API_URL", "http://127.0.0.1:8000").rstrip("/")

REFUSAL_MESSAGE = (
    "I couldn't find that in the Zearn documentation corpus. "
    "Try rephrasing your question, or contact Zearn support for help."
)
FALLBACK_PREFIX = "This wasn't found in Zearn documentation; sourced from the web."

RAG_API_URL = AGENT_API_URL if REMOTE_MODE else LOCAL_API_URL


def run_agent_local(question: str) -> tuple[str, list[dict], dict]:
    """In-process ADK agent — only for local dev (requires google-adk in venv)."""
    from zearn_support_agent import run_zearn_agent

    return run_zearn_agent(question)

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


def api_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("AGENT_API_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def run_agent_remote(
    question: str,
    *,
    session_id: str,
    install_id: str,
    history: list[dict[str, str]],
) -> tuple[str, list[dict]]:
    with httpx.Client(timeout=AGENT_TIMEOUT) as client:
        response = client.post(
            f"{AGENT_API_URL}/agent",
            json={
                "question": question,
                "session_id": session_id,
                "install_id": install_id,
                "history": history,
            },
            headers=api_headers(),
        )
        response.raise_for_status()
        data = response.json()
    return data["answer"], data.get("steps", [])


def memory_get_remote(install_id: str) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{AGENT_API_URL}/memory",
            params={"install_id": install_id},
            headers=api_headers(),
        )
        if response.status_code == 404:
            return {"install_id": install_id}
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, dict) else {"install_id": install_id}


def memory_save_remote(install_id: str, *, role: str, grade_band: str) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{AGENT_API_URL}/memory",
            json={
                "install_id": install_id,
                "role": role,
                "grade_band": grade_band,
                "confirmed_write": True,
            },
            headers=api_headers(),
        )
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, dict) else {"install_id": install_id}


def memory_delete_remote(install_id: str) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.delete(
            f"{AGENT_API_URL}/memory",
            params={"install_id": install_id},
            headers=api_headers(),
        )
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, dict) else {"install_id": install_id}


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

    if REMOTE_MODE:
        st.divider()
        st.subheader("Week 5 Memory demo (Path A)")

        if "install_id" not in st.session_state:
            st.session_state.install_id = uuid.uuid4().hex
        if "session_id" not in st.session_state:
            st.session_state.session_id = uuid.uuid4().hex
        if "agent_history" not in st.session_state:
            st.session_state.agent_history = []
        if "memory_record" not in st.session_state:
            st.session_state.memory_record = None

        role = st.selectbox(
            "Role",
            options=["teacher", "student"],
            index=0,
            key="memory_role",
        )
        grade_band = st.text_input("Grade band", value="Grade 3", key="memory_grade_band")

        if st.button("Save preference", type="primary", use_container_width=True):
            with st.spinner("Saving durable memory…"):
                st.session_state.memory_record = memory_save_remote(
                    st.session_state.install_id,
                    role=role,
                    grade_band=grade_band,
                )
            st.success("Preference saved.")

        if st.button("New session (recall)", use_container_width=True):
            st.session_state.session_id = uuid.uuid4().hex
            st.session_state.agent_history = []
            with st.spinner("Reloading memory and starting new session…"):
                st.session_state.memory_record = memory_get_remote(st.session_state.install_id)

        if st.button("Forget preference", use_container_width=True):
            with st.spinner("Deleting durable memory…"):
                memory_delete_remote(st.session_state.install_id)
                st.session_state.memory_record = {"install_id": st.session_state.install_id}

        st.caption(f"install_id: `{st.session_state.install_id}`")
        st.caption(f"session_id: `{st.session_state.session_id}`")

        # Best-effort load on first render.
        if st.session_state.memory_record is None:
            with st.spinner("Loading saved memory…"):
                try:
                    st.session_state.memory_record = memory_get_remote(st.session_state.install_id)
                except Exception:
                    st.session_state.memory_record = {"install_id": st.session_state.install_id}

        st.markdown("**Retrieved memory**")
        st.json(st.session_state.memory_record)

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
                answer, steps = run_agent_remote(
                    question.strip(),
                    session_id=st.session_state.session_id,
                    install_id=st.session_state.install_id,
                    history=st.session_state.agent_history,
                )
            else:
                answer, steps, _usage = run_agent_local(question.strip())
        except httpx.HTTPStatusError as exc:
            st.error(f"API error {exc.response.status_code}: {exc.response.text[:500]}")
            st.stop()
        except Exception as exc:
            st.error(f"Agent error: {exc}")
            st.stop()

    # Update local in-session history so the agent can use conversational context.
    if REMOTE_MODE:
        st.session_state.agent_history.append(
            {"role": "user", "content": question.strip()}
        )
        st.session_state.agent_history.append(
            {"role": "assistant", "content": answer.strip()}
        )

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
