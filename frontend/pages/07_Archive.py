# cognitive/app/frontend/07_Archive.py
import streamlit as st
import requests
import json
from datetime import date, datetime
from collections import defaultdict
from pathlib import Path

API      = "http://127.0.0.1:8000"
CSS_PATH = Path(__file__).parent.parent.parent / "assets" / "style.css"

st.set_page_config(page_title="Archive", page_icon="🗄️", layout="wide")

# ── CSS ───────────────────────────────────────────────────────────────────────
def inject_css():
    try:
        with open(CSS_PATH, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        pass
inject_css()

# ── Constants ──────────────────────────────────────────────────────────────────
PRIORITY_EMOJI = {
    "Critical": "🔴", "High": "🟠",
    "Medium":   "🟡", "Low":  "🟢", "Overdue": "🚨"
}
PRI_COL = {
    "Critical": "#e8394a", "High": "#d97706",
    "Medium":   "#5b52e8", "Low":  "#1f9e6e",
}
C = {
    "bg":     "#1a1a2e",
    "border": "#2d2d3d",
    "text":   "#e2e8f0",
    "muted":  "#6b7280",
    "green":  "#10b981",
}

st.title("🗄️ Task Archive")
st.caption("Completed tasks older than 24h live here permanently — nothing is ever deleted.")

# ── Fetch archived tasks via API ───────────────────────────────────────────────
@st.cache_data(ttl=15)
def fetch_archived():
    try:
        r = requests.get(f"{API}/tasks", timeout=5)
        if r.status_code != 200:
            return []
        return [t for t in r.json() if t.get("status") == "archived"]
    except Exception:
        return []

tasks = fetch_archived()

# ── Filters ───────────────────────────────────────────────────────────────────
fc1, fc2, fc3 = st.columns([3, 2, 2])
with fc1:
    search = st.text_input("🔍 Search title", placeholder="e.g. report, gym...")
with fc2:
    cat_options = ["All", "Work", "Development", "Personal", "Learning", "Finance", "Other"]
    cat_filter  = st.selectbox("📁 Category", cat_options)
with fc3:
    sort_by = st.selectbox("↕️ Sort", ["Newest first", "Oldest first", "Priority", "Category"])

# ── Apply filters ─────────────────────────────────────────────────────────────
if search:
    tasks = [t for t in tasks if search.lower() in t.get("title", "").lower()]
if cat_filter != "All":
    tasks = [t for t in tasks if t.get("category") == cat_filter]

# ── Sort ──────────────────────────────────────────────────────────────────────
pri_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Other": 4}

def parse_dt(raw):
    if not raw:
        return datetime.min
    try:
        return datetime.fromisoformat(raw.replace("Z", ""))
    except Exception:
        return datetime.min

if sort_by == "Newest first":
    tasks.sort(key=lambda t: parse_dt(t.get("completed_at") or t.get("created_at")), reverse=True)
elif sort_by == "Oldest first":
    tasks.sort(key=lambda t: parse_dt(t.get("completed_at") or t.get("created_at")))
elif sort_by == "Priority":
    tasks.sort(key=lambda t: pri_order.get(t.get("priority", "Other"), 99))
elif sort_by == "Category":
    tasks.sort(key=lambda t: t.get("category") or "")

# ── Stats ─────────────────────────────────────────────────────────────────────
if tasks:
    total_mins = sum(
        (t.get("actual_minutes") or t.get("estimated_minutes") or 0)
        for t in tasks
    )
    today_str  = date.today().isoformat()
    today_done = [
        t for t in tasks
        if (t.get("completed_at") or "")[:10] == today_str
    ]
    cat_counts: dict[str, int] = {}
    for t in tasks:
        c = t.get("category") or "Other"
        cat_counts[c] = cat_counts.get(c, 0) + 1
    top_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "—"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📦 Total Archived",    len(tasks))
    m2.metric("⏱️ Total Hours Done",  f"~{total_mins // 60}h {total_mins % 60}m")
    m3.metric("🏆 Top Category",      top_cat)
    m4.metric("✅ Archived Today",     len(today_done))
    st.divider()

# ── Task list ─────────────────────────────────────────────────────────────────
if not tasks:
    st.info(
        "🗄️ No archived tasks yet.\n\n"
        "Tasks completed more than 24h ago appear here automatically.",
        icon="ℹ️"
    )
else:
    st.markdown(f"**{len(tasks)} archived task(s)**")

    for t in tasks:
        tid     = t.get("id", "?")
        title   = t.get("title", "Untitled")
        pri     = t.get("priority", "Medium")
        cat     = t.get("category", "Other") or "Other"
        est     = t.get("estimated_minutes", 0) or 0
        actual  = t.get("actual_minutes", 0) or 0
        notes   = t.get("notes", "") or ""

        p_icon  = PRIORITY_EMOJI.get(pri, "⚪")
        col     = PRI_COL.get(pri, "#5b52e8")

        # Parse dates
        completed_raw = t.get("completed_at") or ""
        created_raw   = t.get("created_at")   or ""
        done_str      = completed_raw[:16].replace("T", " ") if completed_raw else "Unknown"
        created_str   = created_raw[:10] if created_raw else "Unknown"

        # Time accuracy
        if est and actual:
            diff     = actual - est
            sign     = "+" if diff > 0 else ""
            clr      = "#f59e0b" if abs(diff) > 15 else C["green"]
            time_str = (
                f"<span style='color:{clr};'>⏱️ {actual}min actual · "
                f"{sign}{diff}min vs estimate</span>"
            )
        elif est:
            time_str = f"<span style='color:{C['muted']};'>⏱️ ~{est}min estimated</span>"
        else:
            time_str = ""

        # Energy (uses energy_level_start / energy_level_end from your model)
        e_start = t.get("energy_level_start")
        e_end   = t.get("energy_level_end")
        energy_str = ""
        if e_start and e_end:
            arrow = "↑" if e_end > e_start else ("↓" if e_end < e_start else "→")
            energy_str = (
                f"<span style='color:#8b5cf6;font-size:0.75rem;'>"
                f"⚡ Energy {e_start}→{e_end} {arrow}</span>"
            )

        notes_str = ""
        if notes:
            preview   = notes[:100] + ("..." if len(notes) > 100 else "")
            notes_str = (
                f"<div style='color:{C['muted']};font-size:0.75rem;margin-top:4px;'>"
                f"📝 {preview}</div>"
            )

        st.markdown(f"""
        <div style='background:{C["bg"]};border:1px solid {C["border"]};
                    border-left:4px solid {C["green"]};border-radius:10px;
                    padding:14px 18px;margin-bottom:8px;'>
            <div style='display:flex;justify-content:space-between;
                        align-items:flex-start;flex-wrap:wrap;gap:6px;'>
                <div>
                    <span style='color:{C["muted"]};font-size:0.78rem;'>#{tid}</span>
                    <span style='color:{C["text"]};font-weight:600;font-size:1rem;
                                 margin-left:8px;'>{p_icon} {title}</span>
                    <span style='background:#1f2937;color:#9ca3af;font-size:0.72rem;
                                 padding:2px 8px;border-radius:10px;margin-left:6px;'>
                        {cat}
                    </span>
                </div>
                <div style='text-align:right;font-size:0.78rem;color:{C["muted"]};'>
                    <div>✅ <strong style='color:{C["text"]};'>{done_str}</strong></div>
                    <div>📅 Created: {created_str}</div>
                </div>
            </div>
            <div style='margin-top:6px;display:flex;gap:12px;flex-wrap:wrap;'>
                {time_str}
                {energy_str}
            </div>
            {notes_str}
        </div>
        """, unsafe_allow_html=True)

    # ── Restore action ──────────────────────────────────────────────────────
    st.divider()
    st.markdown("### ♻️ Restore a Task")
    st.caption("Move an archived task back to pending (e.g. it needs to be redone).")

    rc1, rc2 = st.columns([2, 1])
    with rc1:
        restore_id = st.number_input(
            "Task ID to restore",
            min_value=1, step=1,
            value=tasks[0].get("id", 1) if tasks else 1
        )
    with rc2:
        st.write("")
        if st.button("♻️ Restore to Pending", use_container_width=True, type="primary"):
            try:
                r = requests.patch(
                    f"{API}/tasks/{restore_id}",
                    json={"status": "pending", "completed_at": None, "actual_minutes": None},
                    timeout=5,
                )
                if r.status_code == 200:
                    st.success(f"✅ Task #{restore_id} restored to pending!")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(f"Failed: {r.status_code} — {r.text}")
            except Exception as e:
                st.error(f"Connection error: {e}")
