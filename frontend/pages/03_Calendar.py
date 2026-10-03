# cognitive/app/frontend/03_Calendar.py
import streamlit as st
import requests
import json
import calendar
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path

API      = "http://127.0.0.1:8000"
CSS_PATH = Path(__file__).parent.parent.parent / "assets" / "style.css"
PFILE    = Path(__file__).parent.parent.parent / "user_profile.json"

st.set_page_config(page_title="Calendar", layout="wide", page_icon="📅")

# ── Inject CSS ────────────────────────────────────────────────────────────────
def inject_css():
    try:
        with open(CSS_PATH, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning(f"CSS not found: {CSS_PATH}")
inject_css()

# ── Profile ───────────────────────────────────────────────────────────────────
def load_profile():
    if PFILE.exists():
        with open(PFILE) as f:
            return json.load(f)
    return {"daily_goal": 5, "name": ""}

DAILY_GOAL = load_profile().get("daily_goal", 5)

# ── Fetch completed + archived tasks (FIXED: archived tasks stay visible) ─────
@st.cache_data(ttl=30)
def fetch_done_tasks():
    """
    Fetches ALL tasks that were ever completed.
    Includes both 'completed' (recent) and 'archived' (older than 24h).
    This ensures calendar history is never lost after auto-archive runs.
    """
    try:
        r = requests.get(f"{API}/tasks", timeout=5)
        if r.status_code != 200:
            return []
        data = r.json()
        # ✅ KEY FIX: include archived — they have completed_at timestamps
        return [
            t for t in data
            if t.get("status") in ("completed", "archived")
            and (t.get("completed_at") or t.get("created_at"))
        ]
    except Exception:
        return []

all_done      = fetch_done_tasks()
tasks_by_date = defaultdict(list)
for t in all_done:
    # Use completed_at if available, else fall back to created_at
    raw = t.get("completed_at") or t.get("created_at", "")
    if raw:
        tasks_by_date[raw[:10]].append(t)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 📅 Activity Calendar")
st.caption(f"Daily goal: **{DAILY_GOAL} tasks**. Browse days to see what you completed.")

# ── Session state ──────────────────────────────────────────────────────────────
today = date.today()
if "cal_year"  not in st.session_state: st.session_state.cal_year  = today.year
if "cal_month" not in st.session_state: st.session_state.cal_month = today.month

# ── Month nav ──────────────────────────────────────────────────────────────────
nav_l, nav_c, nav_r = st.columns([1, 5, 1])
with nav_l:
    if st.button("← Prev", use_container_width=True):
        if st.session_state.cal_month == 1:
            st.session_state.cal_month = 12
            st.session_state.cal_year -= 1
        else:
            st.session_state.cal_month -= 1
        st.rerun()
with nav_c:
    st.markdown(
        f"<h3 style='text-align:center;margin:0;color:var(--text,#1a1a2e)'>"
        f"{calendar.month_name[st.session_state.cal_month]} "
        f"{st.session_state.cal_year}</h3>",
        unsafe_allow_html=True,
    )
with nav_r:
    if st.button("Next →", use_container_width=True):
        if st.session_state.cal_month == 12:
            st.session_state.cal_month = 1
            st.session_state.cal_year += 1
        else:
            st.session_state.cal_month += 1
        st.rerun()

year  = st.session_state.cal_year
month = st.session_state.cal_month

# ── Streak calculation (goal-based, consecutive days) ─────────────────────────
# A streak day = any day where completed count >= DAILY_GOAL
goal_days: set[str] = set()
for d_str, tasks in tasks_by_date.items():
    if len(tasks) >= DAILY_GOAL:
        goal_days.add(d_str)

# Current streak = consecutive days going backward from today that hit goal
streak_days: set[str] = set()
sd = today
for _ in range(365):
    ds = sd.strftime("%Y-%m-%d")
    if ds in goal_days:
        streak_days.add(ds)
        sd -= timedelta(days=1)
    else:
        # Allow today to not have hit goal yet without breaking streak
        if sd == today:
            sd -= timedelta(days=1)
            continue
        break

current_streak = len(streak_days)

# ── Color theme ────────────────────────────────────────────────────────────────
C = {
    "bg_surface":   "#ffffff",
    "border":       "#e0dfd8",
    "text":         "#1a1a2e",
    "muted":        "#7a788a",
    "accent":       "#5b52e8",
    "accent_lt":    "rgba(91,82,232,0.12)",
    "accent_ring":  "rgba(91,82,232,0.30)",
    "success_lt":   "rgba(31,158,110,0.14)",
    "success_bdr":  "rgba(31,158,110,0.35)",
    "gold_lt":      "rgba(255,215,0,0.12)",
    "gold_bdr":     "rgba(255,215,0,0.35)",
}

# ── Day headers ────────────────────────────────────────────────────────────────
DAY_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
hdr_cols = st.columns(7)
for i, h in enumerate(DAY_HEADERS):
    with hdr_cols[i]:
        st.markdown(
            f"<div style='text-align:center;font-size:0.75rem;font-weight:700;"
            f"color:{C['muted']};padding:6px 0'>{h}</div>",
            unsafe_allow_html=True,
        )

# ── Calendar grid ──────────────────────────────────────────────────────────────
for week in calendar.monthcalendar(year, month):
    cols = st.columns(7)
    for i, day_num in enumerate(week):
        with cols[i]:
            if day_num == 0:
                st.markdown("<div style='height:72px;'></div>", unsafe_allow_html=True)
                continue

            d_str   = f"{year}-{month:02d}-{day_num:02d}"
            d_obj   = date(year, month, day_num)
            count   = len(tasks_by_date.get(d_str, []))
            is_today    = (d_obj == today)
            in_streak   = d_str in streak_days
            beat_goal   = count >= DAILY_GOAL and count > 0
            has_tasks   = count > 0

            # ── Cell styling ──────────────────────────────────────────────────
            if beat_goal:
                bg    = C["gold_lt"]
                bdr   = C["gold_bdr"]
                emoji = "🏆"
            elif in_streak and has_tasks:
                bg    = C["success_lt"]
                bdr   = C["success_bdr"]
                emoji = "🔥"
            elif is_today:
                bg    = C["accent_lt"]
                bdr   = C["accent"]
                emoji = ""
            else:
                bg    = C["bg_surface"]
                bdr   = C["border"]
                emoji = ""

            ring      = f"box-shadow:0 0 0 2px {C['accent_ring']};" if is_today else ""
            num_color = C["accent"] if is_today else C["text"]

            # Sub content: emoji > count dot > nothing
            if emoji:
                sub_html = (
                    f"<div style='font-size:0.85rem;margin-top:2px'>{emoji}</div>"
                    f"<div style='font-size:0.65rem;color:{C['muted']};margin-top:1px'>{count}✓</div>"
                ) if has_tasks else ""

            elif has_tasks:
                sub_html = (
                    f"<div style='width:6px;height:6px;border-radius:50%;"
                    f"background:{C['accent']};margin:4px auto 0'></div>"
                    f"<div style='font-size:0.65rem;color:{C['muted']};margin-top:1px'>"
                    f"{count}✓</div>"
                )
            else:
                sub_html = ""

            st.markdown(
                f"<div title='{count} task{'s' if count != 1 else ''} on {d_str}' "
                f"style='height:72px;border-radius:10px;border:1px solid {bdr};"
                f"background:{bg};display:flex;flex-direction:column;"
                f"align-items:center;justify-content:center;"
                f"margin-bottom:6px;{ring}'>"
                f"<div style='font-size:0.82rem;font-weight:700;color:{num_color};'>"
                f"{day_num}</div>"
                f"{sub_html}"
                f"</div>",
                unsafe_allow_html=True,
            )

# ── Legend ────────────────────────────────────────────────────────────────────
st.markdown(
    f"<div style='display:flex;gap:18px;margin-top:14px;font-size:0.78rem;"
    f"color:{C['muted']};flex-wrap:wrap;align-items:center'>"
    f"<span>🏆 Beat daily goal ({DAILY_GOAL}+ tasks)</span>"
    f"<span>🔥 On streak</span>"
    f"<span style='display:flex;align-items:center;gap:5px'>"
    f"<span style='width:7px;height:7px;border-radius:50%;"
    f"background:{C['accent']};display:inline-block'></span> Tasks done</span>"
    f"<span style='border:1.5px solid {C['accent']};border-radius:6px;"
    f"padding:1px 8px;color:{C['accent']}'>Today</span>"
    f"</div>",
    unsafe_allow_html=True,
)

st.divider()

# ── Browse a Day ──────────────────────────────────────────────────────────────
st.markdown("#### 📋 Browse a Day")
st.caption("Select a date to see tasks completed that day — includes archived tasks.")
selected = st.date_input("Pick date", value=today, label_visibility="collapsed")

if selected:
    sel_str   = selected.strftime("%Y-%m-%d")
    day_tasks = tasks_by_date.get(sel_str, [])

    if not day_tasks:
        st.markdown(
            f"<div style='background:{C['bg_surface']};border:1px solid {C['border']};"
            f"border-radius:12px;padding:32px;text-align:center;"
            f"color:{C['muted']};margin-top:8px'>"
            f"No tasks completed on <b>{sel_str}</b>.</div>",
            unsafe_allow_html=True,
        )
    else:
        goal_met = len(day_tasks) >= DAILY_GOAL
        banner   = "🏆 Goal smashed!" if len(day_tasks) > DAILY_GOAL else "✅ Goal met!" if goal_met else ""
        is_streak_day = sel_str in streak_days

        streak_badge = ""
        if is_streak_day:
            streak_badge = " &nbsp;🔥 streak day"

        st.markdown(
            f"<div style='font-size:0.9rem;color:{C['muted']};margin:8px 0 12px'>"
            f"<b style='color:{C['text']}'>{len(day_tasks)} tasks</b> completed on "
            f"<b style='color:{C['accent']}'>{selected.strftime('%B %d, %Y')}</b>"
            + (f" &nbsp;<span style='color:#d4a017'>{banner}</span>" if banner else "")
            + (f"<span style='color:{C['success_bdr']}'>{streak_badge}</span>")
            + "</div>",
            unsafe_allow_html=True,
        )

        # Progress toward daily goal
        goal_pct = min(len(day_tasks) / DAILY_GOAL, 1.0) if DAILY_GOAL else 0
        st.progress(goal_pct, text=f"Daily goal: {len(day_tasks)}/{DAILY_GOAL} tasks")

        PRI_COL = {
            "Critical": "#e8394a", "High": "#d97706",
            "Medium":   "#5b52e8", "Low":  "#1f9e6e",
        }

        # Sort by completed_at time
        def sort_key(t):
            raw = t.get("completed_at") or t.get("created_at") or ""
            return raw

        for t in sorted(day_tasks, key=sort_key):
            pri    = t.get("priority", "Medium")
            col    = PRI_COL.get(pri, "#5b52e8")
            cat    = t.get("category", "")
            est    = t.get("estimated_minutes", 0)
            act    = t.get("actual_minutes", 0)
            title  = str(t.get("title", ""))
            status = t.get("status", "completed")

            # Time accuracy note
            tnote = ""
            if est and act:
                diff  = act - est
                clr   = "#f59e0b" if abs(diff) > 15 else "#1f9e6e"
                tnote = (
                    f"<span style='color:{clr}'>⏱️ {act}min "
                    f"({'+'if diff>0 else ''}{diff}min vs est.)</span>"
                    if abs(diff) > 5 else
                    f"<span style='color:{C['muted']}'>⏱️ {act}min</span>"
                )
            elif est:
                tnote = f"<span style='color:{C['muted']}'>⏱️ ~{est}min est.</span>"

            # Archived badge
            arch_badge = ""
            if status == "archived":
                arch_badge = (
                    f"<span style='background:#1a1a2e;color:#6b7280;"
                    f"font-size:0.68rem;padding:1px 7px;border-radius:10px;"
                    f"border:1px solid #2d2d3d;margin-left:6px;'>🗄️ archived</span>"
                )

            # Completed time
            raw_ct  = t.get("completed_at", "")
            time_str = raw_ct[11:16] if len(raw_ct) >= 16 else ""
            time_lbl = f"<span style='color:{C['muted']};float:right;font-size:0.75rem;'>✅ {time_str}</span>" if time_str else ""

            st.markdown(f"""
            <div style='background:{C["bg_surface"]};border:1px solid {C["border"]};
                        border-left:3px solid {col};border-radius:12px;
                        padding:14px 18px;margin-bottom:8px;
                        box-shadow:0 1px 4px rgba(0,0,0,.07)'>
                <div style='font-weight:600;color:{C["text"]};display:flex;
                            justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px'>
                    <span>
                        ✅ <span style='color:{C["muted"]};font-size:0.8rem'>#{t["id"]}</span>
                        &nbsp;{title}{arch_badge}
                    </span>
                    {time_lbl}
                </div>
                <div style='font-size:0.78rem;color:{C["muted"]};margin-top:6px;
                            display:flex;gap:10px;flex-wrap:wrap;align-items:center'>
                    <span style='background:{col}20;color:{col};border:1px solid {col}50;
                                 padding:1px 9px;border-radius:20px;font-size:0.7rem;
                                 font-weight:600'>{pri}</span>
                    {'<span>📁 ' + cat + '</span>' if cat else ''}
                    {tnote}
                </div>
            </div>
            """, unsafe_allow_html=True)

# ── Monthly summary ───────────────────────────────────────────────────────────
st.divider()
st.markdown("#### 📊 This Month At a Glance")
prefix  = f"{year}-{month:02d}"
m_total = sum(len(v) for k, v in tasks_by_date.items() if k.startswith(prefix))
m_active = sum(1 for k in tasks_by_date if k.startswith(prefix))
m_beat   = sum(
    1 for k, v in tasks_by_date.items()
    if k.startswith(prefix) and len(v) >= DAILY_GOAL
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Tasks This Month",   m_total)
m2.metric("Active Days",        m_active)
m3.metric("Days Beat Goal 🏆",  m_beat)
m4.metric("Current Streak 🔥",  f"{current_streak}d")