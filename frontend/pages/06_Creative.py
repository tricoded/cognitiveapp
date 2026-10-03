# frontend/pages/06_Creative.py
import streamlit as st
import json
import random
from datetime import date, datetime
from pathlib import Path
import sys

# ── Robust path resolution ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ml.creativity_engine import (
    get_todays_prompt,
    submit_response,
    get_creativity_stats,
    load_log,
    load_prompts,
    has_completed_today,
    get_streak,
)

CSS_PATH = Path(__file__).parent.parent.parent / "assets" / "style.css"
st.set_page_config(page_title="Creative Training", page_icon="🧠", layout="wide")


def inject_css():
    try:
        with open(CSS_PATH, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        pass


inject_css()

# ── Theme ─────────────────────────────────────────────────────────────────────
C = {
    "bg":      "#1a1a2e", "surface": "#1e1e2e", "border": "#2d2d3d",
    "text":    "#e2e8f0", "muted":   "#6b7280", "accent": "#6366f1",
    "green":   "#10b981", "gold":    "#f59e0b", "purple": "#8b5cf6",
}
CAT_COLORS = {
    "Creative Thinking": "#6366f1", "Problem Solving":  "#10b981",
    "Lateral Thinking":  "#f59e0b", "Reframing":        "#8b5cf6",
    "Brain Teaser":      "#ec4899", "Perspective Shift": "#06b6d4",
    "Word Puzzles":      "#f97316", "Logic":            "#22d3ee",
    "Strategic Thinking": "#a78bfa",
}
DIFF_COLORS = {"easy": "#10b981", "medium": "#f59e0b", "hard": "#ef4444"}


# ══════════════════════════════════════════════════════════════════════════════
#  GAME RENDERERS  — defined FIRST so they can be called anywhere below
# ══════════════════════════════════════════════════════════════════════════════

def render_wordle():
    WORD_LIST = [
        "crane", "slate", "audio", "stare", "arise", "blast",
        "chair", "drive", "flute", "grace", "heart", "joust",
        "knack", "plumb", "quirk", "shrug", "twist", "vouch",
        "wrath", "yearn", "zesty", "brisk", "cleft", "dwelt",
    ]

    if "wordle_word" not in st.session_state:
        # Seed by date so the word is consistent all day
        import hashlib
        seed = int(hashlib.md5(date.today().isoformat().encode()).hexdigest(), 16)
        st.session_state.wordle_word    = WORD_LIST[seed % len(WORD_LIST)].upper()
        st.session_state.wordle_guesses = []
        st.session_state.wordle_won     = False

    word      = st.session_state.wordle_word
    guesses   = st.session_state.wordle_guesses
    max_tries = 6

    st.markdown("#### 🟩 Wordle — Guess the Word")

    # ── Keyboard hint tracker ─────────────────────────────────────────────────
    letter_states: dict[str, str] = {}
    for g in guesses:
        for j, letter in enumerate(g.upper()):
            if letter == word[j]:
                letter_states[letter] = "correct"
            elif letter in word and letter_states.get(letter) != "correct":
                letter_states[letter] = "present"
            elif letter not in letter_states:
                letter_states[letter] = "absent"

    # ── Grid ──────────────────────────────────────────────────────────────────
    grid_html = "<div style='display:flex;flex-direction:column;gap:6px;align-items:center;margin:16px 0;'>"
    for i in range(max_tries):
        grid_html += "<div style='display:flex;gap:6px;'>"
        if i < len(guesses):
            guess = guesses[i].upper()
            for j, letter in enumerate(guess):
                if letter == word[j]:
                    bg = "#538d4e"
                elif letter in word:
                    bg = "#b59f3b"
                else:
                    bg = "#3a3a3c"
                grid_html += (
                    f"<div style='width:52px;height:52px;background:{bg};"
                    f"color:white;font-size:1.5rem;font-weight:800;"
                    f"display:flex;align-items:center;justify-content:center;"
                    f"border-radius:6px;border:2px solid {bg};'>{letter}</div>"
                )
        else:
            for _ in range(5):
                border = "#565656" if i == len(guesses) else "#3a3a3c"
                grid_html += (
                    f"<div style='width:52px;height:52px;background:#121213;"
                    f"border:2px solid {border};border-radius:6px;'></div>"
                )
        grid_html += "</div>"
    grid_html += "</div>"
    st.markdown(grid_html, unsafe_allow_html=True)

    # ── On-screen keyboard ────────────────────────────────────────────────────
    rows = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
    kb_html = "<div style='display:flex;flex-direction:column;align-items:center;gap:6px;margin-bottom:16px;'>"
    for row in rows:
        kb_html += "<div style='display:flex;gap:4px;'>"
        for ch in row:
            state = letter_states.get(ch, "unused")
            bg    = {"correct": "#538d4e", "present": "#b59f3b",
                     "absent": "#3a3a3c", "unused": "#818384"}[state]
            kb_html += (
                f"<div style='width:34px;height:34px;background:{bg};color:white;"
                f"font-size:0.75rem;font-weight:700;display:flex;"
                f"align-items:center;justify-content:center;"
                f"border-radius:4px;'>{ch}</div>"
            )
        kb_html += "</div>"
    kb_html += "</div>"
    st.markdown(kb_html, unsafe_allow_html=True)

    # ── Input ─────────────────────────────────────────────────────────────────
    if not st.session_state.wordle_won and len(guesses) < max_tries:
        col_in, col_btn = st.columns([3, 1])
        with col_in:
            guess_input = st.text_input(
                "Your guess (5 letters):", max_chars=5,
                key=f"wordle_input_{len(guesses)}",
                label_visibility="collapsed",
                placeholder="Type a 5-letter word...",
            ).upper().strip()
        with col_btn:
            if st.button("Guess →", type="primary", use_container_width=True):
                if len(guess_input) == 5 and guess_input.isalpha():
                    st.session_state.wordle_guesses.append(guess_input)
                    if guess_input == word:
                        st.session_state.wordle_won = True
                    st.rerun()
                else:
                    st.warning("Enter exactly 5 letters!")

    if st.session_state.wordle_won:
        st.success(f"🎉 Brilliant! You found **{word}** in {len(guesses)} {'try' if len(guesses)==1 else 'tries'}!")
        st.balloons()
    elif len(guesses) >= max_tries:
        st.error(f"The word was **{word}**. Better luck tomorrow!")

    if st.button("🔄 New Word (practice)"):
        for key in ["wordle_word", "wordle_guesses", "wordle_won"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()


def render_sudoku():
    st.markdown("#### 🔢 Sudoku Sprint")

    PUZZLE = [
        [5, 3, 0,  0, 7, 0,  0, 0, 0],
        [6, 0, 0,  1, 9, 5,  0, 0, 0],
        [0, 9, 8,  0, 0, 0,  0, 6, 0],
        [8, 0, 0,  0, 6, 0,  0, 0, 3],
        [4, 0, 0,  8, 0, 3,  0, 0, 1],
        [7, 0, 0,  0, 2, 0,  0, 0, 6],
        [0, 6, 0,  0, 0, 0,  2, 8, 0],
        [0, 0, 0,  4, 1, 9,  0, 0, 5],
        [0, 0, 0,  0, 8, 0,  0, 7, 9],
    ]
    SOLUTION = [
        [5, 3, 4,  6, 7, 8,  9, 1, 2],
        [6, 7, 2,  1, 9, 5,  3, 4, 8],
        [1, 9, 8,  3, 4, 2,  5, 6, 7],
        [8, 5, 9,  7, 6, 1,  4, 2, 3],
        [4, 2, 6,  8, 5, 3,  7, 9, 1],
        [7, 1, 3,  9, 2, 4,  8, 5, 6],
        [9, 6, 1,  5, 3, 7,  2, 8, 4],
        [2, 8, 7,  4, 1, 9,  6, 3, 5],
        [3, 4, 5,  2, 8, 6,  1, 7, 9],
    ]

    if "sudoku_grid" not in st.session_state:
        st.session_state.sudoku_grid = [row[:] for row in PUZZLE]

    # ── Grid ──────────────────────────────────────────────────────────────────
    for i in range(9):
        cols = st.columns(9)
        for j in range(9):
            # Add visual 3x3 box separator via background
            box_bg = "#1a1a2e" if (i // 3 + j // 3) % 2 == 0 else "#1e1e2e"
            if PUZZLE[i][j] != 0:
                cols[j].markdown(
                    f"<div style='text-align:center;font-weight:800;font-size:1.1rem;"
                    f"padding:8px 0;color:#6366f1;background:{box_bg};"
                    f"border-radius:4px;'>{PUZZLE[i][j]}</div>",
                    unsafe_allow_html=True,
                )
            else:
                val = cols[j].number_input(
                    " ",
                    min_value=0, max_value=9,
                    value=int(st.session_state.sudoku_grid[i][j]),
                    key=f"cell_{i}_{j}",
                    label_visibility="collapsed",
                )
                st.session_state.sudoku_grid[i][j] = int(val)

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Check Solution", type="primary", use_container_width=True):
            if st.session_state.sudoku_grid == SOLUTION:
                st.success("🎉 Perfect! Sudoku solved!")
                st.balloons()
            else:
                # Find how many cells are correct
                correct = sum(
                    1 for i in range(9) for j in range(9)
                    if st.session_state.sudoku_grid[i][j] == SOLUTION[i][j]
                )
                filled = sum(
                    1 for i in range(9) for j in range(9)
                    if PUZZLE[i][j] == 0 and st.session_state.sudoku_grid[i][j] != 0
                )
                empty_cells = sum(1 for row in PUZZLE for v in row if v == 0)
                st.error(f"Not quite — {correct}/{empty_cells + sum(1 for row in PUZZLE for v in row if v != 0)} cells correct. Keep going!")
    with c2:
        if st.button("🔄 Reset", use_container_width=True):
            del st.session_state["sudoku_grid"]
            st.rerun()


def render_chess():
    st.markdown("#### ♟️ Chess Puzzle — White to Move, Checkmate in 2")
    st.markdown(
        """<div style='background:#1e1e2e;border:1px solid #2d2d3d;border-radius:12px;
                        padding:20px;text-align:center;margin-bottom:16px;'>
            <div style='display:inline-grid;grid-template-columns:repeat(8,52px);
                        grid-template-rows:repeat(8,52px);border:2px solid #3a3a3c;
                        border-radius:4px;overflow:hidden;'>
        """ +
        "".join(
            f"<div style='background:{'#f0d9b5' if (r+c)%2==0 else '#b58863'};"
            f"display:flex;align-items:center;justify-content:center;"
            f"font-size:2rem;'>{piece}</div>"
            for r, row in enumerate([
                ["", "", "", "", "", "", "♚", ""],
                ["", "", "", "", "♙", "", "", ""],
                ["", "", "", "", "", "♙", "", ""],
                ["", "", "", "", "", "", "", ""],
                ["", "", "", "", "", "", "", ""],
                ["", "", "", "", "", "", "", ""],
                ["", "", "", "", "", "", "", ""],
                ["", "♔", "", "", "", "", "", ""],
            ])
            for c, piece in enumerate(row)
        ) +
        "</div></div>",
        unsafe_allow_html=True,
    )

    col_in, col_btn = st.columns([3, 1])
    with col_in:
        ans = st.text_input(
            "Your move:", key="chess_answer",
            placeholder="e.g. Qh5, Rg8, Nf7...",
            label_visibility="collapsed",
        )
    with col_btn:
        if st.button("Check ♟️", type="primary", use_container_width=True):
            correct_moves = ["qh5", "q-h5", "queen h5", "queen to h5"]
            if ans.lower().strip() in correct_moves:
                st.success("♟️ Brilliant! Qh5+ is the move!")
            else:
                st.warning("Not quite — think about cutting off ALL escape squares.")

    with st.expander("💡 Show solution"):
        st.markdown("**1. Qh5+ Kf8 2. Qf7#** — The Queen controls h5, forcing the king to f8, then Qf7 is checkmate.")


def render_text_prompt(prompt: dict, C: dict, CAT_COLORS: dict, DIFF_COLORS: dict):
    """Renders the standard text-response challenge card + form."""
    cat_color  = CAT_COLORS.get(prompt.get("category", ""), C["accent"])
    diff_color = DIFF_COLORS.get(prompt.get("difficulty", "easy"), C["muted"])

    # ── Prompt card ───────────────────────────────────────────────────────────
    st.markdown(
        f"""<div style='background:{C["surface"]};border:1px solid {C["border"]};
                        border-left:5px solid {cat_color};border-radius:14px;
                        padding:24px 28px;margin-bottom:20px;'>
            <div style='display:flex;justify-content:space-between;
                        align-items:flex-start;flex-wrap:wrap;gap:8px;margin-bottom:14px;'>
                <div>
                    <span style='background:{cat_color}22;color:{cat_color};
                                 font-size:0.75rem;font-weight:700;padding:3px 12px;
                                 border-radius:20px;border:1px solid {cat_color}44;'>
                        {prompt.get("category","?")}
                    </span>
                    <span style='background:{diff_color}22;color:{diff_color};
                                 font-size:0.72rem;font-weight:600;padding:3px 10px;
                                 border-radius:20px;border:1px solid {diff_color}44;
                                 margin-left:8px;'>
                        {prompt.get("difficulty","?").upper()}
                    </span>
                </div>
                <div style='color:{C["muted"]};font-size:0.78rem;'>
                    📅 {date.today().strftime("%B %d, %Y")}
                </div>
            </div>
            <h3 style='color:{C["text"]};margin:0 0 12px 0;font-size:1.25rem;'>
                {prompt.get("title","?")}
            </h3>
            <p style='color:{C["text"]};font-size:1rem;line-height:1.65;margin:0;'>
                {prompt.get("prompt","?")}
            </p>
        </div>""",
        unsafe_allow_html=True,
    )

    with st.expander("💡 Show hint", expanded=False):
        st.markdown(
            f"<div style='color:{C['muted']};font-style:italic;padding:4px 0;'>"
            f"{prompt.get('hint','')}</div>",
            unsafe_allow_html=True,
        )

    done_today = has_completed_today()

    if done_today:
        log     = load_log()
        today   = date.today().isoformat()
        t_entry = next(
            (e for e in reversed(log.get("entries", []))
             if e.get("date") == today and e.get("completed")),
            None,
        )
        st.success("✅ You completed today's challenge!", icon="🎉")
        if t_entry and t_entry.get("response"):
            st.markdown("**Your response:**")
            st.markdown(
                f"<div style='background:{C['bg']};border:1px solid {C['border']};"
                f"border-radius:10px;padding:16px;color:{C['text']};'>"
                f"{t_entry['response']}</div>",
                unsafe_allow_html=True,
            )
            r = t_entry.get("rating", 3)
            st.markdown(f"**Your rating:** {'⭐' * r}")
        st.markdown("**Come back tomorrow for a new challenge!**")

    else:
        st.markdown("#### ✍️ Your Response")
        st.caption("No right or wrong answers. Quality of thinking beats length every time.")

        response = st.text_area(
            "Your answer",
            placeholder="Start typing your response here...",
            height=200,
            label_visibility="collapsed",
            key="creative_response",
        )

        col_rate, col_time = st.columns(2)
        with col_rate:
            rating = st.select_slider(
                "⭐ How valuable was this prompt?",
                options=[1, 2, 3, 4, 5],
                value=3,
                format_func=lambda x: {
                    1: "1 — Not useful", 2: "2 — Meh", 3: "3 — OK",
                    4: "4 — Good",       5: "5 — Excellent!",
                }[x],
            )
        with col_time:
            time_spent = st.slider("⏱️ Time spent (minutes)", 1, 60, 10, step=1)

        submit_disabled = len(response.strip()) < 10
        if st.button("✅ Submit Response", use_container_width=True,
                     type="primary", disabled=submit_disabled):
            result     = submit_response(
                prompt_id=prompt["id"],
                response=response.strip(),
                rating=rating,
                time_spent=time_spent,
            )
            new_streak = result.get("streak", 0)
            st.success("🎉 Response saved! Great work.")
            st.balloons()
            if new_streak >= 7:
                st.markdown(
                    f"<div style='background:{C['gold']}22;border:1px solid {C['gold']}44;"
                    f"border-radius:10px;padding:14px;color:{C['gold']};margin-top:8px;'>"
                    f"🔥 <strong>{new_streak}-day streak!</strong> Unstoppable.</div>",
                    unsafe_allow_html=True,
                )
            elif new_streak >= 3:
                st.markdown(
                    f"<div style='background:{C['green']}22;border:1px solid {C['green']}44;"
                    f"border-radius:10px;padding:14px;color:{C['green']};margin-top:8px;'>"
                    f"⚡ <strong>{new_streak}-day streak!</strong></div>",
                    unsafe_allow_html=True,
                )
            st.rerun()

        if submit_disabled and response.strip():
            st.caption("Write at least 10 characters to submit.")


def render_puzzle(prompt: dict, C: dict, CAT_COLORS: dict, DIFF_COLORS: dict):
    """Route to the correct game renderer based on prompt type."""
    if prompt is None:
        st.error("⚠️ Could not load prompts. Make sure data/prompts.json exists.")
        return

    ptype = prompt.get("type", "text")

    # Show category + difficulty badge for all types
    cat_color  = CAT_COLORS.get(prompt.get("category", ""), C["accent"])
    diff_color = DIFF_COLORS.get(prompt.get("difficulty", "easy"), C["muted"])
    st.markdown(
        f"<div style='margin-bottom:16px;'>"
        f"<span style='background:{cat_color}22;color:{cat_color};font-size:0.75rem;"
        f"font-weight:700;padding:3px 12px;border-radius:20px;"
        f"border:1px solid {cat_color}44;'>{prompt.get('category','?')}</span>"
        f"<span style='background:{diff_color}22;color:{diff_color};font-size:0.72rem;"
        f"font-weight:600;padding:3px 10px;border-radius:20px;"
        f"border:1px solid {diff_color}44;margin-left:8px;'>"
        f"{prompt.get('difficulty','?').upper()}</span>"
        f"<span style='color:{C['muted']};font-size:0.78rem;margin-left:12px;'>"
        f"📅 {date.today().strftime('%B %d, %Y')}</span></div>",
        unsafe_allow_html=True,
    )

    if ptype == "wordle":
        render_wordle()
    elif ptype == "sudoku":
        render_sudoku()
    elif ptype == "chess":
        render_chess()
    else:
        render_text_prompt(prompt, C, CAT_COLORS, DIFF_COLORS)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE HEADER
# ══════════════════════════════════════════════════════════════════════════════
st.title("🧠 Creative & Problem Solving Training")
st.caption(
    "One daily challenge to sharpen your thinking. "
    "Personalized over time — the more you engage, the better it fits you."
)

# ── Stats bar ─────────────────────────────────────────────────────────────────
stats      = get_creativity_stats()
streak     = get_streak()
done_today = has_completed_today()

s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("🔥 Current Streak",  f"{streak} day{'s' if streak != 1 else ''}")
s2.metric("✅ Total Completed", stats.get("total_completed", 0))
s3.metric("⭐ Avg Rating",
          f"{stats['avg_rating']}/5" if stats.get("avg_rating") else "—")
s4.metric("⏱️ Time Invested",
          f"~{stats['total_time_mins'] // 60}h {stats['total_time_mins'] % 60}m"
          if stats.get("total_time_mins") else "—")
s5.metric("🏆 Fave Category",   stats.get("favorite_category") or "—")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_today, tab_history, tab_browse = st.tabs([
    "🎯 Today's Challenge",
    "📖 My Journal",
    "🗂️ Browse All Prompts",
])

# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — TODAY'S CHALLENGE
# ══════════════════════════════════════════════════════════════════════════════
with tab_today:
    prompt = get_todays_prompt()

    if not prompt:
        st.error(
            "⚠️ Could not load prompts. "
            "Make sure **data/prompts.json** exists at the project root."
        )
        st.stop()

    # ── Streak badges ─────────────────────────────────────────────────────────
    if done_today and streak >= 7:
        st.markdown(
            f"<div style='background:{C['gold']}22;border:1px solid {C['gold']}44;"
            f"border-radius:10px;padding:10px 16px;color:{C['gold']};margin-bottom:12px;'>"
            f"🔥 <strong>{streak}-day streak!</strong> You're on fire.</div>",
            unsafe_allow_html=True,
        )
    elif done_today and streak >= 3:
        st.markdown(
            f"<div style='background:{C['green']}22;border:1px solid {C['green']}44;"
            f"border-radius:10px;padding:10px 16px;color:{C['green']};margin-bottom:12px;'>"
            f"⚡ <strong>{streak}-day streak!</strong> Keep it alive.</div>",
            unsafe_allow_html=True,
        )

    # ── Render the right puzzle type ──────────────────────────────────────────
    render_puzzle(prompt, C, CAT_COLORS, DIFF_COLORS)

    # ── Category preference bars ──────────────────────────────────────────────
    cat_scores = stats.get("category_scores", {})
    if cat_scores:
        st.divider()
        st.markdown("#### 🎯 Your Category Preferences")
        st.caption("Based on your ratings — the engine adapts future prompts to what you find valuable.")
        max_score = max(cat_scores.values()) if cat_scores else 1
        for cat, score in sorted(cat_scores.items(), key=lambda x: -x[1]):
            bar_w   = max(2, int(score / max_score * 100))
            cat_col = CAT_COLORS.get(cat, C["accent"])
            pct     = round(score * 100)
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;"
                f"margin-bottom:6px;font-size:0.83rem;'>"
                f"<span style='width:140px;color:{C['muted']};'>{cat}</span>"
                f"<div style='flex:1;background:{C['border']};border-radius:4px;height:14px;'>"
                f"<div style='width:{bar_w}%;background:{cat_col};"
                f"border-radius:4px;height:14px;'></div></div>"
                f"<span style='color:{C['text']};width:36px;text-align:right;'>{pct}%</span>"
                f"</div>",
                unsafe_allow_html=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — JOURNAL
# ══════════════════════════════════════════════════════════════════════════════
with tab_history:
    st.markdown("#### 📖 Your Response Journal")
    st.caption("Every prompt you've completed, with your responses saved.")

    log          = load_log()
    prompts_list = load_prompts()
    done_entries = [e for e in log.get("entries", []) if e.get("completed")]

    if not done_entries:
        st.info("No completed challenges yet. Start with today's prompt! 🎯", icon="📭")
    else:
        done_sorted = sorted(done_entries, key=lambda e: e.get("date", ""), reverse=True)
        st.markdown(f"**{len(done_sorted)} challenges completed**")

        for entry in done_sorted:
            pid  = entry.get("prompt_id")
            p    = next((x for x in prompts_list if x["id"] == pid), None)
            if not p:
                continue
            d_str    = entry.get("date", "?")
            resp     = entry.get("response", "")
            rating   = entry.get("rating", 3)
            t_spent  = entry.get("time_spent", 0) or 0
            cat_col  = CAT_COLORS.get(p.get("category", ""), C["accent"])

            with st.expander(
                f"{'⭐' * rating}  **{p['title']}** — {d_str}  ·  {p['category']}",
                expanded=False,
            ):
                st.markdown(
                    f"<span style='background:{cat_col}22;color:{cat_col};"
                    f"font-size:0.75rem;padding:2px 10px;border-radius:12px;"
                    f"border:1px solid {cat_col}44;'>{p['category']}</span>"
                    f"&nbsp;&nbsp;<span style='color:{C['muted']};font-size:0.78rem;'>"
                    f"⏱️ {t_spent}min · {d_str}</span>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"**Prompt:** {p['prompt']}")
                st.divider()
                if resp:
                    st.markdown("**Your response:**")
                    st.markdown(
                        f"<div style='background:{C['bg']};border:1px solid {C['border']};"
                        f"border-radius:8px;padding:14px;color:{C['text']};'>{resp}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("*(No text response — puzzle type)*")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — BROWSE
# ══════════════════════════════════════════════════════════════════════════════
with tab_browse:
    st.markdown("#### 🗂️ All Prompts")
    st.caption("Browse the full prompt bank. Filter by category or difficulty.")

    all_prompts = load_prompts()
    if not all_prompts:
        st.error("❌ data/prompts.json not found. Create it at your project root.")
        st.stop()

    bf1, bf2, bf3 = st.columns(3)
    with bf1:
        cats     = ["All"] + sorted(set(p.get("category", "") for p in all_prompts))
        cat_filt = st.selectbox("Category", cats, key="browse_cat")
    with bf2:
        diffs     = ["All", "easy", "medium", "hard"]
        diff_filt = st.selectbox("Difficulty", diffs, key="browse_diff")
    with bf3:
        types      = ["All", "text", "wordle", "sudoku", "chess"]
        type_filt  = st.selectbox("Type", types, key="browse_type")

    filtered = all_prompts
    if cat_filt  != "All": filtered = [p for p in filtered if p.get("category") == cat_filt]
    if diff_filt != "All": filtered = [p for p in filtered if p.get("difficulty") == diff_filt]
    if type_filt != "All": filtered = [p for p in filtered if p.get("type", "text") == type_filt]

    st.markdown(f"**{len(filtered)} prompt(s)**")

    completed_ids = {
        e["prompt_id"] for e in load_log().get("entries", []) if e.get("completed")
    }
    TYPE_ICON = {"text": "✍️", "wordle": "🟩", "sudoku": "🔢", "chess": "♟️"}

    for p in filtered:
        cat_col  = CAT_COLORS.get(p.get("category", ""), C["accent"])
        diff_col = DIFF_COLORS.get(p.get("difficulty", "easy"), C["muted"])
        done_lbl = "✅ " if p["id"] in completed_ids else ""
        t_icon   = TYPE_ICON.get(p.get("type", "text"), "✍️")

        with st.expander(
            f"{done_lbl}{t_icon} **{p['title']}** · {p.get('category','?')} · {p.get('difficulty','?').upper()}",
            expanded=False,
        ):
            st.markdown(
                f"<span style='background:{cat_col}22;color:{cat_col};"
                f"font-size:0.75rem;padding:2px 10px;border-radius:12px;"
                f"border:1px solid {cat_col}44;'>{p.get('category','?')}</span>"
                f"&nbsp;"
                f"<span style='background:{diff_col}22;color:{diff_col};"
                f"font-size:0.72rem;padding:2px 10px;border-radius:12px;"
                f"border:1px solid {diff_col}44;margin-left:4px;'>"
                f"{p.get('difficulty','?').upper()}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(f"\n**{p.get('prompt','?')}**")
            st.caption(f"💡 Hint: {p.get('hint','')}")
