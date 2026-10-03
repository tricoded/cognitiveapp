# cognitive/app/frontend/02_Tasks.py
import streamlit as st
import requests
import html as html_module
from pathlib import Path

API = "http://127.0.0.1:8000"

st.set_page_config(page_title="Tasks", layout="wide", page_icon="📋")

# ── Inject CSS ────────────────────────────────────────────────────────────────
CSS_PATH = Path(__file__).parent.parent.parent / "assets" / "style.css"
def inject_css():
    try:
        with open(CSS_PATH, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning(f"CSS not found at: {CSS_PATH}")
inject_css()

# ── Shared inline style helpers (no class dependency) ────────────────────────
def S(bg="var(--bg-surface)", border="var(--border)", extra=""):
    """Base card style — fully inline."""
    return (
        f"background:{bg};border:1px solid {border};border-radius:12px;"
        f"padding:16px 20px;margin-bottom:10px;"
        f"box-shadow:0 1px 4px rgba(0,0,0,.07);{extra}"
    )

PCOL = {
    "Critical": "#e8394a",
    "Overdue":  "#e8394a",
    "High":     "#d97706",
    "Medium":   "#5b52e8",
    "Low":      "#1f9e6e",
}
PORD = {"Critical": 0, "Overdue": 0, "High": 1, "Medium": 2, "Low": 3}

# ── Fetch ─────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=5)
def fetch_tasks():
    try:
        r = requests.get(f"{API}/tasks", timeout=5)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        return []

tasks     = fetch_tasks()
pending   = [t for t in tasks if t.get("status") in ("pending", "in_progress")]
completed = [t for t in tasks if t.get("status") == "completed"]
p_sorted  = sorted(pending, key=lambda t: PORD.get(t.get("priority", "Medium"), 99))

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 📋 Tasks")
st.caption("Manage, complete, and prioritize your work.")

# ── Stats ─────────────────────────────────────────────────────────────────────
total    = len(tasks)
done_n   = len(completed)
rate     = round(done_n / total * 100) if total else 0
critical = sum(1 for t in pending if t.get("priority") in ("Critical", "Overdue"))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Pending",         len(pending))
c2.metric("Completed",       done_n)
c3.metric("Completion Rate", f"{rate}%")
c4.metric("Critical Now",    critical)
st.divider()

# ── Quick Add ─────────────────────────────────────────────────────────────────
with st.expander("➕ Add Task", expanded=False):
    with st.form("add_task_form", clear_on_submit=True):
        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
        title    = col1.text_input("Title", placeholder="What needs to be done?")
        priority = col2.selectbox("Priority", ["Medium", "High", "Critical", "Low"])
        category = col3.selectbox("Category", ["Work","Personal","Development","Learning","Finance"])
        est      = col4.number_input("Est. Minutes", 15, 480, 60, step=15)
        if st.form_submit_button("➕ Add Task", use_container_width=True):
            if title.strip():
                try:
                    r = requests.post(f"{API}/tasks", json={
                        "title": title.strip(), "priority": priority,
                        "category": category, "estimated_minutes": est,
                        "status": "pending",
                    }, timeout=5)
                    if r.status_code in (200, 201):
                        st.success("✅ Task added!")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(f"API error {r.status_code}: {r.text}")
                except requests.exceptions.ConnectionError:
                    st.error("Cannot reach API. Is the backend running?")
            else:
                st.warning("Please enter a task title.")

st.divider()

# ── Pending ───────────────────────────────────────────────────────────────────
st.markdown(
    f"#### ⏳ Pending "
    f"<span style='color:var(--muted,#888);font-size:0.82rem;font-weight:400'>"
    f"— {len(p_sorted)} tasks</span>",
    unsafe_allow_html=True,
)

if not p_sorted:
    st.markdown(
        f"<div style='{S()}text-align:center;padding:40px 20px;"
        f"color:var(--muted,#888)'>🎉 All clear! Add a task above.</div>",
        unsafe_allow_html=True,
    )
else:
    for task in p_sorted:
        pri   = task.get("priority", "Medium")
        color = PCOL.get(pri, "#5b52e8")
        tid   = task["id"]
        ttl   = html_module.escape(str(task.get("title", "")))
        cat   = html_module.escape(str(task.get("category", "")))
        est   = task.get("estimated_minutes", 0)
        due   = task.get("due_date", "")

        badge_style = (
            f"display:inline-block;padding:2px 10px;border-radius:20px;"
            f"font-size:0.7rem;font-weight:600;letter-spacing:0.03em;"
            f"background:{color}20;color:{color};border:1px solid {color}50"
        )
        due_html = (
            f"<span style='color:var(--warning,#d97706)'>📅 {due[:10]}</span>"
            if due else ""
        )
        est_html = f"<span>⏱️ {est}min</span>" if est else ""

        # Card — 100% inline, no class dependency
        st.markdown(f"""
        <div style='{S(extra=f"border-left:3px solid {color}")}'>
            <div style='font-weight:600;font-size:0.95rem;
                        color:var(--text,#1a1a2e);margin-bottom:6px'>
                <span style='color:var(--muted,#888);font-size:0.8rem'>#{tid}</span>
                &nbsp; {ttl}
            </div>
            <div style='font-size:0.78rem;color:var(--muted,#888);
                        display:flex;gap:10px;align-items:center;flex-wrap:wrap'>
                <span style='{badge_style}'>{pri}</span>
                {'<span>📁 ' + cat + '</span>' if cat else ''}
                {est_html}
                {due_html}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Action row
        b1, b2, b3, _, b5 = st.columns([2, 2, 2, 2, 1])

        # Complete
        if b1.button("✅ Complete", key=f"done_{tid}"):
            try:
                r = requests.patch(
                    f"{API}/tasks/{tid}",
                    json={"status": "completed"},
                    timeout=5,
                )
                if r.status_code in (200, 204):
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(f"Failed ({r.status_code}): {r.text}")
            except requests.exceptions.ConnectionError:
                st.error("Cannot reach API.")

        # Priority update
        valid_pris = ["Critical", "High", "Medium", "Low"]
        new_pri = b2.selectbox(
            "Priority", valid_pris,
            index=valid_pris.index(pri) if pri in valid_pris else 2,
            key=f"pri_sel_{tid}",
            label_visibility="collapsed",
        )
        if b3.button("Update", key=f"upd_{tid}"):
            try:
                r = requests.patch(
                    f"{API}/tasks/{tid}",
                    json={"priority": new_pri},
                    timeout=5,
                )
                if r.status_code in (200, 204):
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(f"Failed ({r.status_code}): {r.text}")
            except requests.exceptions.ConnectionError:
                st.error("Cannot reach API.")

        # Delete
        if b5.button("🗑️", key=f"del_{tid}", help="Delete task"):
            st.session_state[f"confirm_{tid}"] = True

        if st.session_state.get(f"confirm_{tid}"):
            st.markdown(
                f"<div style='background:#e8394a10;border:1px solid #e8394a30;"
                f"border-radius:10px;padding:10px 14px;font-size:0.85rem;"
                f"color:var(--text,#1a1a2e);margin-top:4px'>"
                f"🗑️ Delete <b>#{tid} — {ttl}</b>? This cannot be undone.</div>",
                unsafe_allow_html=True,
            )
            y, n = st.columns(2)
            if y.button("Yes, delete", key=f"yes_{tid}", type="primary"):
                try:
                    r = requests.delete(f"{API}/tasks/{tid}", timeout=5)
                    if r.status_code in (200, 204):
                        st.cache_data.clear()
                        del st.session_state[f"confirm_{tid}"]
                        st.rerun()
                    else:
                        st.error(f"Failed ({r.status_code}): {r.text}")
                except requests.exceptions.ConnectionError:
                    st.error("Cannot reach API.")
            if n.button("Cancel", key=f"no_{tid}"):
                del st.session_state[f"confirm_{tid}"]
                st.rerun()

# ── Completed ─────────────────────────────────────────────────────────────────
st.divider()
with st.expander(f"✅ Completed — {len(completed)} tasks", expanded=False):
    if not completed:
        st.caption("No completed tasks yet.")
    else:
        for task in reversed(completed[-20:]):
            act   = task.get("actual_minutes")
            est   = task.get("estimated_minutes", 0)
            note  = f"· {act}min actual" if act else (f"· ~{est}min est." if est else "")
            ttl   = html_module.escape(str(task.get("title", "")))
            st.markdown(
                f"<div style='{S()}opacity:0.65'>"
                f"<span style='color:var(--success,#1f9e6e)'>✅</span> "
                f"<b>#{task['id']}</b> {ttl} "
                f"<span style='color:var(--muted,#888);font-size:0.78rem'>{note}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )