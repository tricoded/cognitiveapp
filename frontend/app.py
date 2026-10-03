import streamlit as st
from utils.api import health_check

# ── Page Config ──────────────────────────────────────────
st.set_page_config(
    page_title="Cognitive Assistant",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ── Header ───────────────────────────────────────────────
st.title("🧠 Cognitive Assistant")
st.caption("Your local AI-powered memory assistant — running 100% on your machine.")

st.divider()

# ── Backend Status ───────────────────────────────────────
st.subheader("🔌 Backend Status")

with st.spinner("Checking connection to backend..."):
    status = health_check()

if "error" not in str(status.get("status", "")):
    st.success("FastAPI backend is online and healthy.")
else:
    st.error("Cannot reach the FastAPI backend. Is uvicorn running?")
    st.caption(f"Details: {status.get('detail', 'unknown error')}")
    st.code("venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000", language="bash")

st.divider()

# ── Navigation Guide ─────────────────────────────────────
st.subheader("📌 Navigation")

# Replace the col1, col2, col3 navigation block in app.py with:

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.info("💬 **Chat**\nTalk to your AI assistant")
with col2:
    st.info("🗃️ **Memory**\nBrowse stored memories")
with col3:
    st.info("✅ **Tasks**\nManage your task list")
with col4:
    st.info("⚙️ **Settings**\nConfigure model options")
    
st.divider()
st.caption("Built with FastAPI + Ollama + Streamlit · Running locally · No data leaves your machine 🔒")
