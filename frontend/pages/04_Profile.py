# cognitive/app/frontend/04_Profile.py
import streamlit as st
import json
from datetime import datetime
from pathlib import Path

CSS_PATH = Path(__file__).parent.parent.parent / "assets" / "style.css"
PFILE    = Path(__file__).parent.parent.parent / "user_profile.json"

st.set_page_config(page_title="Profile", layout="centered", page_icon="👤")

def inject_css():
    try:
        with open(CSS_PATH, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning(f"CSS not found: {CSS_PATH}")
inject_css()

# ── Card helper ───────────────────────────────────────────────────────────────
def card(content: str, accent_color: str = ""):
    border = f"border-left:3px solid {accent_color};" if accent_color else ""
    st.markdown(
        f"<div style='background:var(--bg-surface,#fff);"
        f"border:1px solid var(--border,#e0dfd8);{border}"
        f"border-radius:12px;padding:18px 22px;margin-bottom:10px;"
        f"box-shadow:0 1px 4px rgba(0,0,0,.07)'>{content}</div>",
        unsafe_allow_html=True,
    )

# ── Load / Save ───────────────────────────────────────────────────────────────
def load_profile() -> dict:
    if PFILE.exists():
        with open(PFILE) as f:
            return json.load(f)
    return {
        "name": "", "work_start_hour": 9, "work_end_hour": 18,
        "daily_goal": 5, "timezone": "UTC",
        "signed_in": False, "signed_in_at": None,
    }

def save_profile(p: dict):
    PFILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PFILE, "w") as f:
        json.dump(p, f, indent=2, default=str)

if "profile" not in st.session_state:
    st.session_state.profile = load_profile()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 👤 Your Profile")
st.caption("Set your working hours and daily goals. These power your AI-driven schedule.")
st.divider()

# ── Sign in/out ───────────────────────────────────────────────────────────────
col_s, col_a = st.columns([2, 1])
is_in     = st.session_state.profile.get("signed_in", False)
in_at     = st.session_state.profile.get("signed_in_at", "")

if is_in:
    card(
        f"<span style='color:var(--success,#1f9e6e);font-weight:700;font-size:1rem'>"
        f"● Work Session Active</span><br>"
        f"<span style='color:var(--muted,#888);font-size:0.82rem'>"
        f"Started at {in_at[:16] if in_at else '—'}</span>",
        accent_color="var(--success,#1f9e6e)",
    )
    if col_a.button("🚪 Sign Out", use_container_width=True):
        st.session_state.profile.update({"signed_in": False, "signed_in_at": None})
        save_profile(st.session_state.profile)
        st.success("Session ended. Great work! 👏")
        st.rerun()
else:
    with col_s:
        card(
            "<span style='color:var(--muted,#888);font-weight:600'>● Not signed in</span><br>"
            "<span style='color:var(--muted,#888);font-size:0.82rem'>"
            "Sign in to start your work session</span>"
        )
    if col_a.button("✅ Sign In", use_container_width=True):
        st.session_state.profile.update({
            "signed_in": True,
            "signed_in_at": datetime.now().isoformat(),
        })
        save_profile(st.session_state.profile)
        st.success("Session started! Let's go 🚀")
        st.rerun()

st.divider()

# ── Form ──────────────────────────────────────────────────────────────────────
with st.form("profile_form"):
    st.markdown("#### ⚙️ Preferences")
    name = st.text_input(
        "Your name",
        value=st.session_state.profile.get("name", ""),
        placeholder="e.g. Alex",
    )
    st.markdown("#### 🕐 Working Hours")
    wc1, wc2 = st.columns(2)
    work_start = wc1.slider("Work starts at", 5, 12,
                             st.session_state.profile.get("work_start_hour", 9), format="%d:00")
    work_end   = wc2.slider("Work ends at",  13, 23,
                             st.session_state.profile.get("work_end_hour",  18), format="%d:00")
    st.markdown("#### 🎯 Daily Goal")
    st.caption("Calendar shows 🏆 when you beat this.")
    daily_goal = st.slider("Tasks / day", 1, 20,
                            st.session_state.profile.get("daily_goal", 5))
    st.markdown("#### 🌍 Timezone")
    tz_opts  = ["UTC","US/Eastern","US/Central","US/Pacific",
                "Europe/London","Europe/Paris","Asia/Tokyo",
                "Asia/Singapore","Asia/Kolkata","Australia/Sydney"]
    saved_tz = st.session_state.profile.get("timezone", "UTC")
    tz = st.selectbox("Timezone", tz_opts,
                      index=tz_opts.index(saved_tz) if saved_tz in tz_opts else 0)

    if st.form_submit_button("Save Profile ✅", use_container_width=True):
        st.session_state.profile.update({
            "name": name, "work_start_hour": work_start,
            "work_end_hour": work_end, "daily_goal": daily_goal, "timezone": tz,
        })
        save_profile(st.session_state.profile)
        st.success("Profile saved! ✅")

st.divider()

# ── Summary ───────────────────────────────────────────────────────────────────
p = st.session_state.profile
if p.get("name"):
    card(
        f"<span style='font-size:1.1rem;font-weight:700;"
        f"color:var(--text,#1a1a2e)'>{p['name']}</span><br><br>"
        f"<span style='color:var(--muted,#888);font-size:0.83rem'>"
        f"🕐 {p['work_start_hour']}:00 – {p['work_end_hour']}:00"
        f" &nbsp;·&nbsp; 🎯 {p['daily_goal']} tasks/day"
        f" &nbsp;·&nbsp; 🌍 {p['timezone']}</span>",
        accent_color="var(--accent,#5b52e8)",
    )