import streamlit as st
import requests
from datetime import datetime
import time

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="Cognitive · Chat",
    page_icon="💬",
    layout="wide",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .user-bubble {
        background: #1e40af;
        color: white;
        padding: 0.85rem 1.2rem;
        border-radius: 18px 18px 4px 18px;
        margin: 0.4rem 0 0.4rem 15%;
        line-height: 1.6;
        word-wrap: break-word;
    }
    .ai-bubble {
        background: #1f2937;
        color: #f3f4f6;
        border: 1px solid #374151;
        padding: 0.85rem 1.2rem;
        border-radius: 18px 18px 18px 4px;
        margin: 0.4rem 15% 0.4rem 0;
        line-height: 1.6;
        word-wrap: break-word;
    }
    .badge-intent {
        font-size: 0.68rem;
        padding: 2px 8px;
        border-radius: 20px;
        background: #374151;
        color: #9ca3af;
        display: inline-block;
        margin-bottom: 6px;
    }
    .badge-action {
        font-size: 0.7rem;
        padding: 2px 10px;
        border-radius: 20px;
        background: #064e3b;
        color: #6ee7b7;
        display: inline-block;
        margin-bottom: 6px;
    }
    .badge-wizard {
        font-size: 0.7rem;
        padding: 2px 10px;
        border-radius: 20px;
        background: #1e3a5f;
        color: #93c5fd;
        display: inline-block;
        margin-bottom: 6px;
    }
    .badge-deadline {
        font-size: 0.7rem;
        padding: 2px 10px;
        border-radius: 20px;
        background: #451a03;
        color: #fed7aa;
        display: inline-block;
        margin-bottom: 6px;
    }
    .timestamp {
        font-size: 0.65rem;
        color: #6b7280;
        margin-top: 4px;
    }
    #MainMenu, footer { visibility: hidden; }
    .stChatInput {
        position: fixed !important;
        bottom: 1rem;
        left: 0;
        right: 0;
        padding: 0 2rem;
        z-index: 999;
        background: transparent;
    }
    .main .block-container {
        padding-bottom: 6rem !important;
    }
</style>
""", unsafe_allow_html=True)

# ── Session State ──────────────────────────────────────────────────────────
defaults = {
    "messages":               [],
    "conv_history":           [],
    "priority_review_active": False,
    "priority_review_queue":  [],
    "priority_refresh_done":  False,
    "total_tasks_at_load":    0,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ── Priority refresh on first load ────────────────────────────────────────
if "priority_refresh_done" not in st.session_state:
    try:
        # Trigger refresh via a backend call or direct db call
        r = requests.post(f"{API_BASE}/tasks/refresh-priorities", timeout=5)
        if r.ok:
            escalated = r.json().get("escalated", [])
            if escalated:
                names = [e["title"] for e in escalated[:3]]
                st.toast(
                    f"⚡ {len(escalated)} task(s) escalated: {', '.join(names)}",
                    icon="🔴"
                )
    except Exception:
        pass
    st.session_state.priority_refresh_done = True

# ── Header ─────────────────────────────────────────────────────────────────
col_title, col_clear = st.columns([5, 1])
with col_title:
    st.title("💬 Cognitive AI Chat")
    if st.session_state.priority_review_active:
        remaining = len(st.session_state.priority_review_queue)
        st.info(
            f"🎯 **Priority Review Mode** — {remaining} task(s) remaining. "
            f"Reply **C / H / M / L / S** · Say *'stop'* to exit.",
            icon="🧭",
        )
    else:
        st.caption("Your AI productivity coach — knows your tasks, patterns, and goals.")

with col_clear:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🗑️ Clear", use_container_width=True):
        st.session_state.messages               = []
        st.session_state.conv_history           = []
        st.session_state.priority_review_active = False
        st.session_state.priority_review_queue  = []
        st.rerun()

# ── Quick Actions (hidden during wizard) ──────────────────────────────────
triggered = None
if not st.session_state.priority_review_active:
    with st.expander("⚡ Quick Actions", expanded=True):
        q1, q2, q3, q4, q5, q6 = st.columns(6)
        quick_map = {
            q1: ("📋 My Tasks",       "Show me all my pending tasks"),
            q2: ("📅 Plan My Day",    "Plan my day"),
            q3: ("📊 My Stats",       "Show my stats"),
            q4: ("🧭 Prioritize",     "Review priorities"),
            q5: ("⚡ Quick Win",      "What's a quick task I can knock out in under 30 minutes?"),
            q6: ("🔮 Time Estimate",  "How long will my high priority tasks actually take?"),
        }
        for col, (label, prompt) in quick_map.items():
            with col:
                if st.button(label, use_container_width=True):
                    triggered = prompt

st.divider()

# ── Chat History ───────────────────────────────────────────────────────────
with st.container():
    if not st.session_state.messages:
        st.markdown("""
        <div style="text-align:center; padding: 2.5rem 1rem; color:#6b7280;">
            <div style="font-size:3rem">🧠</div>
            <h3 style="color:#9ca3af;">Hey, I'm Cognitive!</h3>
            <p>Your personal AI productivity coach. I know your tasks, deadlines, and patterns.</p>
            <p style="font-size:0.9rem; margin-top:1rem;">
                Try: <em>"Add a task to submit report by Friday"</em> ← I'll auto-set priority from the deadline<br>
                Or: <em>"Plan my day"</em> · <em>"Show my stats"</em> · <em>"Review priorities"</em><br>
                Or just: <em>"hi"</em> for a smart morning briefing
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        for msg in st.session_state.messages:
            ts = msg.get("time", "")
            if msg["role"] == "user":
                st.markdown(f"""
                <div class="user-bubble">
                    {msg["content"]}
                    <div class="timestamp" style="text-align:right">{ts}</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                intent     = msg.get("intent", "")
                action     = msg.get("action_taken")
                badge_html = ""

                if intent and intent not in (
                    "general_chat", "priority_review_step", "priority_review_done", "error"
                ):
                    label = intent.replace("_", " ").title()
                    badge_html += f'<span class="badge-intent">🎯 {label}</span> '

                if intent in ("priority_review_step", "priority_review_done", "review_priorities"):
                    badge_html += '<span class="badge-wizard">🧭 Priority Wizard</span> '

                if action:
                    act = action.get("action", "")
                    if act == "task_created":
                        tid     = action.get("task_id", "?")
                        due     = action.get("due_date")
                        due_lbl = f" · due {due}" if due else ""
                        badge_html += f'<span class="badge-action">✅ Task #{tid} created{due_lbl}</span> '
                    elif act == "priority_updated":
                        badge_html += '<span class="badge-action">✅ Priority updated</span> '
                    elif act == "bulk_priority_updated":
                        count = len(action.get("task_ids", []))
                        badge_html += f'<span class="badge-action">✅ {count} priorities updated</span> '
                    elif act == "task_completed":
                        badge_html += '<span class="badge-action">✅ Marked complete</span> '

                if badge_html:
                    badge_html += "<br>"

                content_html = msg["content"].replace("\n", "<br>")
                st.markdown(f"""
                <div class="ai-bubble">
                    {badge_html}{content_html}
                    <div class="timestamp">{ts}</div>
                </div>
                """, unsafe_allow_html=True)

# In your chat display section of 01_Chat.py
def stream_response(text: str, placeholder):
    """Simulate streaming for instant-feel responses."""
    displayed = ""
    for char in text:
        displayed += char
        placeholder.markdown(displayed + "▌")
        time.sleep(0.008)   # adjust speed: 0.005 = fast, 0.015 = slower
    placeholder.markdown(displayed)

    # Usage — replace direct st.markdown(reply) with:
    if reply:
        with st.chat_message("assistant"):
            placeholder = st.empty()
            stream_response(reply, placeholder)

# ── Send Logic ─────────────────────────────────────────────────────────────
def send_message(text: str):
    if not text.strip():
        return

    # ── Wizard exit — caught on frontend before hitting backend ───────────
    if st.session_state.priority_review_active and \
       text.strip().lower() in ("stop", "exit", "cancel", "quit"):
        st.session_state.priority_review_active = False
        st.session_state.priority_review_queue  = []
        st.session_state.messages.append({
            "role":         "assistant",
            "content":      "✅ Priority review stopped. Say *'show my tasks'* to see where things stand.",
            "intent":       "priority_review_done",
            "action_taken": None,
            "time":         datetime.now().strftime("%H:%M"),
        })
        st.rerun()
        return

    now = datetime.now().strftime("%H:%M")
    st.session_state.messages.append({"role": "user", "content": text, "time": now})
    st.session_state.conv_history.append({"role": "user", "content": text})

    with st.spinner("Thinking..."):
        try:
            resp = requests.post(
                f"{API_BASE}/ai/chat",
                json={
                    "message":              text,
                    "conversation_history": st.session_state.conv_history[-6:],
                    "session_state": {
                        "priority_review_active": st.session_state.priority_review_active,
                        "priority_review_queue":  st.session_state.priority_review_queue,
                    },
                },
                timeout=180,
            )
            resp.raise_for_status()
            data   = resp.json()
            reply  = data.get("reply", "Sorry, something went wrong.")
            intent = data.get("intent", "general_chat")
            action = data.get("action_taken")

            # Apply session state updates from backend
            session_update = data.get("session_update", {})
            if "priority_review_active" in session_update:
                st.session_state.priority_review_active = session_update["priority_review_active"]
            if "priority_review_queue" in session_update:
                st.session_state.priority_review_queue = session_update["priority_review_queue"]

        except requests.exceptions.Timeout:
            reply  = "⏱️ Took too long. Try again or check the backend is running."
            intent = "error"
            action = None
        except requests.exceptions.ConnectionError:
            reply  = "⚠️ Can't reach the backend. Make sure `uvicorn app.main:app --reload` is running."
            intent = "error"
            action = None
        except Exception as e:
            reply  = f"⚠️ Error: {str(e)}"
            intent = "error"
            action = None

    st.session_state.messages.append({
        "role":         "assistant",
        "content":      reply,
        "intent":       intent,
        "action_taken": action,
        "time":         datetime.now().strftime("%H:%M"),
    })
    st.session_state.conv_history.append({"role": "assistant", "content": reply})
    st.rerun()


# ── Triggers ───────────────────────────────────────────────────────────────
if triggered:
    send_message(triggered)

placeholder = (
    "Reply C / H / M / L / S for priority · 'stop' to exit..."
    if st.session_state.priority_review_active
    else "Ask me anything — tasks, plans, stats, or just chat..."
)
user_input = st.chat_input(placeholder)
if user_input:
    send_message(user_input)

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📊 Live Snapshot")
    try:
        r = requests.get(f"{API_BASE}/tasks", timeout=5)
        if r.ok:
            all_tasks = r.json()
            pending   = [t for t in all_tasks if t["status"] in ("pending", "in_progress")]
            completed = [t for t in all_tasks if t["status"] == "completed"]
            total     = len(all_tasks)

            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("⏳ Pending",  len(pending))
            with col_b:
                st.metric("✅ Done",     len(completed))

            rate = round(len(completed) / total * 100, 1) if total else 0
            st.progress(rate / 100, text=f"{rate}% complete")

            if pending:
                st.markdown("---")
                order = {"Overdue": 0, "Critical": 1, "High": 2, "Medium": 3, "Low": 4}
                top3  = sorted(pending, key=lambda t: order.get(t.get("priority", "Medium"), 99))[:3]

                st.markdown("**🔥 Focus Now:**")
                icons = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢", "Overdue": "🚨"}
                for t in top3:
                    icon    = icons.get(t.get("priority", "Medium"), "⚪")
                    mins    = t.get("estimated_minutes", "?")
                    title   = t["title"][:26] + ("…" if len(t["title"]) > 26 else "")
                    due_str = ""
                    if t.get("due_date"):
                        due_str = " 📅"
                    st.markdown(f"{icon} {title}{due_str} `{mins}m`")

                total_min = sum(t.get("estimated_minutes") or 60 for t in pending)
                h, m = divmod(total_min, 60)
                st.caption(f"⏱️ ~{h}h {m}min of work remaining")

            # ── Overdue warning ──────────────────────────────────────────
            from datetime import date
            today   = date.today().isoformat()
            overdue = [
                t for t in pending
                if t.get("due_date") and t["due_date"][:10] < today
            ]
            if overdue:
                st.warning(f"🚨 {len(overdue)} task(s) overdue!", icon="⚠️")

    except Exception:
        st.info("Backend offline")

    st.markdown("---")

    # ── Wizard progress bar ────────────────────────────────────────────
    if st.session_state.priority_review_active:
        queue     = st.session_state.priority_review_queue
        remaining = len(queue)

        # ✅ BUG FIX: track total at wizard start to compute real progress
        if "wizard_total" not in st.session_state or st.session_state.get("wizard_total", 0) < remaining:
            st.session_state.wizard_total = remaining

        total_wiz = st.session_state.get("wizard_total", remaining)
        done_wiz  = max(0, total_wiz - remaining)
        progress  = done_wiz / total_wiz if total_wiz > 0 else 0.0

        st.markdown("**🧭 Priority Review**")
        st.progress(progress, text=f"{done_wiz}/{total_wiz} reviewed · {remaining} left")

        if st.button("✖ Stop Review", use_container_width=True):
            st.session_state.priority_review_active = False
            st.session_state.priority_review_queue  = []
            st.session_state.wizard_total            = 0
            st.rerun()
        st.markdown("---")

    # ── Quick Commands reference ───────────────────────────────────────
    with st.expander("💡 Quick Commands", expanded=False):
        st.markdown("""
**Add:**
`add a task to [title], [priority], [time]`
`add a task to submit report by Friday` ← auto-priority!

**Complete:** `complete task #X`

**Priority:**
`set task #X priority to high`
`set tasks #1 high, #2 low` ← bulk
`review priorities` ← wizard

**Plan:** `plan my day`
**Stats:** `show my stats`
**Help:** `help`
        """)

    st.markdown("---")
    st.caption(f"🕐 {datetime.now().strftime('%H:%M')} · Cognitive v1.0")