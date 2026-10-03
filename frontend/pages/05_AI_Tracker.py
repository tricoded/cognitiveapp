# pages/05_AI_Tracker.py
import streamlit as st
import sys
import requests
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import defaultdict
from streamlit_autorefresh import st_autorefresh
import time

sys.path.append(str(Path(__file__).parent.parent))

st.set_page_config(page_title="AI Tracker", page_icon="🤖", layout="wide")

css_path = Path(__file__).parent.parent / "style.css"
if css_path.exists():
    with open(css_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

API = "http://127.0.0.1:8000"

# ─────────────────────────────────────────────────────────────────────────────
# ✅ REAL Auto-refresh every 5 seconds — this ACTUALLY works
# ─────────────────────────────────────────────────────────────────────────────
refresh_count = st_autorefresh(interval=5000, limit=None, key="ai_tracker_refresh")

# ─────────────────────────────────────────────────────────────────────────────
# NO CACHING - Fresh fetch every time
# ─────────────────────────────────────────────────────────────────────────────
def fetch_today_data():
    try:
        response = requests.get(f"{API}/ai-usage/today", timeout=4)
        return response.json()
    except Exception as e:
        return {"total_mins": 0, "budget_mins": 120, "pct_used": 0, "over_budget": False, "logs": []}

def fetch_logs(days: int):
    try:
        return requests.get(f"{API}/ai-usage/?days={days}", timeout=4).json()
    except Exception:
        return []

def fetch_stats(days: int):
    try:
        return requests.get(f"{API}/ai-usage/stats?days={days}", timeout=4).json()
    except Exception:
        return {"message": "No data yet", "days": days}

# ─────────────────────────────────────────────────────────────────────────────
TOOLS = [
    "ChatGPT", "Claude", "Gemini", "Copilot", "Midjourney",
    "Stable Diffusion", "Perplexity", "Notion AI", "Cursor", "Other"
]
CATEGORIES = ["Writing", "Coding", "Research", "Creative", "Decision-making",
              "Learning", "Summarizing", "Brainstorming", "Other"]
QUALITY_OPTIONS = {
    "active":  "🧠 Active — enhanced my thinking",
    "passive": "📋 Passive — copy-paste / shortcuts",
}

# ─────────────────────────────────────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.title("🤖 AI Use Tracker")
st.caption("Track how you use AI tools daily — build healthy habits, measure quality over quantity.")

col1, col2, col3 = st.columns([1, 1, 4])
with col1:
    if st.button("🔄 Refresh Now", use_container_width=True):
        st.rerun()
with col2:
    # Show live pulse indicator so you KNOW it's refreshing
    st.caption(f"⚡ Live · tick #{refresh_count}")

# ─────────────────────────────────────────────────────────────────────────────
#  TODAY'S SUMMARY BAR
# ─────────────────────────────────────────────────────────────────────────────
today_data  = fetch_today_data()
total_today = today_data.get("total_mins", 0)
ai_budget   = today_data.get("budget_mins", 120)
pct_used    = today_data.get("pct_used", 0)
over_budget = today_data.get("over_budget", False)
today_logs  = today_data.get("logs", [])

b1, b2, b3, b4 = st.columns(4)
b1.metric("🕐 AI Used Today",  f"{total_today}min")
b2.metric("🎯 Daily Budget",   f"{ai_budget}min")
b3.metric("📊 Budget Used",    f"{pct_used}%")
b4.metric("📋 Sessions Today", len(today_logs))

budget_color = "#ef4444" if over_budget else "#10b981"
budget_pct   = min(pct_used / 100, 1.0)
st.markdown(
    f"""<div style="background:#1e1e2e; border-radius:8px; padding:4px; margin-bottom:4px;">
    <div style="height:10px; width:{budget_pct*100:.1f}%; background:{budget_color};
                border-radius:8px; transition:width 0.3s;"></div></div>
    <div style="font-size:0.75rem; color:{'#ef4444' if over_budget else '#6b7280'};">
        {'⚠️ Over your AI budget for today!' if over_budget else f'{ai_budget - total_today}min remaining today'}
    </div>""",
    unsafe_allow_html=True,
)

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
#  ACTIVE SESSIONS (from extension)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 🟢 Active Sessions (Not Yet Logged)")
st.caption("Sessions being tracked by your extension in real-time.")

col_a1, col_a2 = st.columns(2)
with col_a1:
    st.info("💡 Sessions auto-log after 30 min of active time or when you close the tab.")
with col_a2:
    if st.button("📤 Force Save Active Sessions", use_container_width=True):
        st.info("Click 'Save & View Sessions' in your extension popup to manually save them.")

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
#  LOG NEW SESSION
# ─────────────────────────────────────────────────────────────────────────────
query_params     = st.query_params
prefill_tool     = query_params.get("tool", None)
prefill_duration = query_params.get("duration", None)
prefill_messages = query_params.get("messages", None)

if prefill_tool:
    st.info(f"📥 Auto-detected session: **{prefill_tool}** ({prefill_duration}min, {prefill_messages} messages)")

default_tool_idx = TOOLS.index(prefill_tool) if prefill_tool and prefill_tool in TOOLS else 0
default_duration = int(prefill_duration) if prefill_duration and prefill_duration.isdigit() else 30
default_notes    = f"Auto-tracked from extension · {prefill_messages} messages" if prefill_messages else ""

with st.expander("➕ Log an AI Session Manually", expanded=(len(today_logs) == 0 or bool(prefill_tool))):
    st.markdown("#### Log what you used AI for right now")

    lc1, lc2 = st.columns(2)
    with lc1:
        tool     = st.selectbox("🤖 AI Tool", TOOLS, index=default_tool_idx, key="log_tool")
        category = st.selectbox("📁 Category", CATEGORIES, key="log_cat")
    with lc2:
        duration = st.slider("⏱️ Duration (minutes)", 5, 240, default_duration, step=5, key="log_dur")
        quality  = st.radio(
            "🧠 How did you use it?",
            list(QUALITY_OPTIONS.keys()),
            format_func=lambda k: QUALITY_OPTIONS[k],
            key="log_quality",
            horizontal=True,
        )

    notes = st.text_area("📝 Notes (optional)", value=default_notes,
                         placeholder="What were you working on?", height=80, key="log_notes")

    if st.button("✅ Log Session", use_container_width=True, type="primary"):
        payload = {
            "tool_name":     tool,
            "category":      category,
            "duration_mins": duration,
            "quality":       quality,
            "notes":         notes or None,
        }
        try:
            r = requests.post(f"{API}/ai-usage/", json=payload, timeout=4)
            if r.status_code == 201:
                st.success(f"✅ Logged {duration}min of {tool} for {category}!")
                time.sleep(0.2)
                st.rerun()
            else:
                st.error(f"Failed to log: {r.text}")
        except Exception as e:
            st.error(f"Connection error: {e}")

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
#  STATS SECTION
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("## 📊 Usage Analytics")

days_tab, week_tab, all_tab = st.tabs(["Last 7 Days", "Last 30 Days", "All Time"])

def render_stats(days: int):
    stats = fetch_stats(days)

    if stats.get("message") == "No data yet":
        st.info("No AI usage logged yet. Use the form above or close an AI tab!", icon="🤖")
        return

    total    = stats.get("total_mins", 0)
    by_day   = stats.get("by_day", {})
    by_cat   = stats.get("by_category", {})
    by_tool  = stats.get("by_tool", {})
    act_pct  = stats.get("active_pct", 0)
    sessions = stats.get("session_count", 0)
    avg_sess = stats.get("avg_session_mins", 0)

    tm1, tm2, tm3, tm4 = st.columns(4)
    tm1.metric("⏱️ Total AI Time", f"{total // 60}h {total % 60}m")
    tm2.metric("📋 Sessions",      sessions)
    tm3.metric("⏱️ Avg Session",   f"{avg_sess:.0f}min")
    tm4.metric("🧠 Active Use %",  f"{act_pct:.0f}%",
               delta="good" if act_pct >= 60 else "low",
               delta_color="normal" if act_pct >= 60 else "inverse")

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### 📅 Daily Usage")
        if by_day:
            max_val = max(by_day.values()) if by_day else 1
            for day_lbl, mins in sorted(by_day.items(), key=lambda x: x[0]):
                bar_w = max(2, int(mins / max_val * 100))
                st.markdown(
                    f"""<div style="display:flex;align-items:center;gap:8px;
                                   margin-bottom:4px;font-size:0.82rem;">
                        <span style="width:56px;color:#9ca3af;">{day_lbl}</span>
                        <div style="flex:1;background:#2d2d3d;border-radius:4px;height:16px;">
                            <div style="width:{bar_w}%;background:#6366f1;
                                        border-radius:4px;height:16px;"></div>
                        </div>
                        <span style="color:#e2e8f0;width:50px;text-align:right;">
                            {mins}min
                        </span>
                    </div>""",
                    unsafe_allow_html=True,
                )

    with col_right:
        st.markdown("#### 📁 By Category")
        if by_cat:
            max_c = max(by_cat.values()) if by_cat else 1
            for cat, mins in sorted(by_cat.items(), key=lambda x: -x[1]):
                bar_w = max(2, int(mins / max_c * 100))
                st.markdown(
                    f"""<div style="display:flex;align-items:center;gap:8px;
                                   margin-bottom:4px;font-size:0.82rem;">
                        <span style="width:100px;color:#9ca3af;">{cat}</span>
                        <div style="flex:1;background:#2d2d3d;border-radius:4px;height:16px;">
                            <div style="width:{bar_w}%;background:#10b981;
                                        border-radius:4px;height:16px;"></div>
                        </div>
                        <span style="color:#e2e8f0;width:50px;text-align:right;">
                            {mins}min
                        </span>
                    </div>""",
                    unsafe_allow_html=True,
                )

    st.markdown("#### 🤖 By Tool")
    if by_tool:
        tool_cols = st.columns(min(len(by_tool), 4))
        for i, (tool_name, mins) in enumerate(sorted(by_tool.items(), key=lambda x: -x[1])[:4]):
            with tool_cols[i % 4]:
                st.markdown(
                    f"""<div style="background:#1e1e2e;border:1px solid #2d2d3d;
                                   border-radius:10px;padding:12px;text-align:center;">
                        <div style="font-size:1.4rem;">🤖</div>
                        <div style="font-weight:600;color:#e2e8f0;font-size:0.9rem;">
                            {tool_name}
                        </div>
                        <div style="color:#6366f1;font-size:0.85rem;">
                            {mins // 60}h {mins % 60}m
                        </div>
                    </div>""",
                    unsafe_allow_html=True,
                )

    st.markdown("#### 🧠 Active vs Passive Use")
    active_mins  = stats.get("active_mins", 0)
    passive_mins = stats.get("passive_mins", 0)
    total_q      = active_mins + passive_mins or 1

    st.markdown(
        f"""<div style="background:#1e1e2e;border-radius:10px;padding:16px;margin-top:8px;">
            <div style="display:flex;gap:0;border-radius:8px;overflow:hidden;height:24px;">
                <div style="width:{active_mins/total_q*100:.1f}%;background:#10b981;"></div>
                <div style="width:{passive_mins/total_q*100:.1f}%;background:#f59e0b;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:8px;
                        font-size:0.8rem;color:#9ca3af;">
                <span>🧠 Active: {active_mins}min ({active_mins/total_q*100:.0f}%)</span>
                <span>📋 Passive: {passive_mins}min ({passive_mins/total_q*100:.0f}%)</span>
            </div>
            <div style="margin-top:8px;font-size:0.82rem;
                        color:{'#10b981' if act_pct >= 60 else '#f59e0b'};">
                {'✅ Great! Most of your AI use enhances your thinking.' if act_pct >= 60
                 else '⚠️ Most AI use is passive. Try to engage more critically.'}
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

with days_tab: render_stats(7)
with week_tab: render_stats(30)
with all_tab:  render_stats(365)

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
#  SESSION HISTORY
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("## 🗂️ Session History (Last 30 Days)")

all_logs = fetch_logs(30)

if not all_logs:
    st.info("No sessions logged yet. Open Gemini/ChatGPT and close the tab!", icon="📭")
else:
    st.markdown(f"**{len(all_logs)} sessions in the last 30 days**")
    for log in all_logs[:50]:
        used_at       = log.get("used_at", "")
        dt_str        = used_at[:16].replace("T", " ") if used_at else "?"
        qual_icon     = "🧠" if log.get("quality") == "active" else "📋"
        notes_s       = log.get("notes") or ""
        notes_preview = f"<div style='color:#6b7280;font-size:0.75rem;margin-top:3px;'>📝 {notes_s[:80]}</div>" if notes_s else ""

        del_col, info_col = st.columns([5, 1])
        with info_col:
            if st.button("🗑️", key=f"del_{log['id']}", help="Delete this log"):
                try:
                    requests.delete(f"{API}/ai-usage/{log['id']}", timeout=4)
                    st.rerun()
                except Exception:
                    st.error("Delete failed")

        st.markdown(
            f"""<div style="background:#1a1a2e;border:1px solid #2d2d3d;
                           border-left:4px solid #6366f1;border-radius:8px;
                           padding:10px 14px;margin-bottom:6px;">
                <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:4px;">
                    <div>
                        {qual_icon}
                        <strong style="color:#e2e8f0;">{log.get('tool_name','?')}</strong>
                        <span style="background:#1e1e3f;color:#a5b4fc;font-size:0.72rem;
                                     padding:2px 8px;border-radius:10px;margin-left:6px;">
                            {log.get('category','?')}
                        </span>
                    </div>
                    <div style="color:#6b7280;font-size:0.8rem;">
                        ⏱️ {log.get('duration_mins','?')}min · {dt_str}
                    </div>
                </div>
                {notes_preview}
            </div>""",
            unsafe_allow_html=True,
        )

# ─────────────────────────────────────────────────────────────────────────────
#  TIPS
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
with st.expander("💡 How This Works"):
    st.markdown("""
    **🔄 Real-Time Tracking**
    - Your extension runs in the background, tracking time & messages on AI sites
    - Every 30 seconds, it checks your activity
    - When you close a tab, it auto-sends the session data to your backend
    - **This page auto-refreshes every 5 seconds** to show new data instantly

    **🧠 Active vs Passive**
    - **Active**: You send 3+ messages (real engagement)
    - **Passive**: 0-2 messages (mostly copy-paste)

    **📊 What Gets Tracked**
    - Time on site · Number of messages sent · Which AI tool · Quality of use

    **💾 Data Stays Local**
    All data syncs to your local backend. You own your data. No cloud tracking!
    """)