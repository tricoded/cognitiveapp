# pages/08_Risk_Dashboard.py
"""Risk, data quality, experiment and analyst views over the warehouse."""

from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Risk & Data", page_icon="🛡️", layout="wide")
API = "http://127.0.0.1:8000"
BANDIT_IMG = Path(__file__).resolve().parents[2] / "docs" / "img" / "bandit_convergence.png"


def get(path, **params):
    try:
        r = requests.get(f"{API}{path}", params=params, timeout=10)
        return r.json() if r.ok else None
    except Exception:
        return None


st.title("🛡️ Risk & Data")
st.caption("Offline Spark warehouse → risk model → real-time decisions. Population data is synthetic; 'Me' is real.")

tab_me, tab_risk, tab_dq, tab_exp, tab_ask = st.tabs(
    ["🧠 Me (CDI)", "🚩 Risky users", "🩺 Data quality", "🧪 Nudge experiment", "💬 Ask the data"]
)

# ── Me ────────────────────────────────────────────────────────────────────────
with tab_me:
    days = st.radio("Window", [7, 14, 30], horizontal=True, format_func=lambda d: f"{d} days")
    cdi = get("/cdi/me", days=days)
    if not cdi:
        st.error("API unreachable.")
    elif cdi.get("cdi") is None:
        st.info(cdi.get("message"))
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cognitive Dependency Index", f"{cdi['cdi']:.0f} / 100", cdi["band"])
        c2.metric("AI minutes", cdi["ai_minutes"])
        c3.metric("Tasks completed", cdi["tasks_completed"])
        c4.metric("AI min per completed task", cdi["ai_minutes_per_completed_task"] or "–")
        comp = pd.DataFrame({"component": list(cdi["components"]),
                             "score (0-1)": list(cdi["components"].values()),
                             "weight": [cdi["weights"][k] for k in cdi["components"]]})
        st.bar_chart(comp.set_index("component")["score (0-1)"])
        st.caption("delegation = 'do it for me' prompts · reask = re-asking loops · night = 00–06h · intensity = AI minutes vs budget")

# ── Risky users ───────────────────────────────────────────────────────────────
with tab_risk:
    card = get("/risk/model")
    if not card:
        st.warning("No model yet. Run `make all` to build the warehouse and train.")
    else:
        m = pd.DataFrame(card["metrics"]).T
        st.subheader("Out-of-time model comparison")
        st.caption(f"train {card['train_dates'][0]}..{card['train_dates'][1]} · test {card['test_dates'][0]}..{card['test_dates'][1]}")
        st.dataframe(m.style.format("{:.3f}").highlight_max(axis=0), use_container_width=True)

        top = get("/risk/users", top=50)
        if top:
            df = pd.DataFrame(top)
            st.subheader(f"Top risky users on {df['dt'].iloc[0]}")
            dist = get("/risk/score-distribution")
            if dist:
                st.bar_chart(pd.DataFrame(dist).set_index("bin")["users"])
            st.dataframe(df, use_container_width=True, hide_index=True)
            uid = st.selectbox("Explain a user", df["user_id"])
            if st.button("Write case note"):
                with st.spinner("Analyst agent is reviewing the evidence..."):
                    ex = get(f"/risk/users/{uid}/explain")
                if ex:
                    st.info(ex["case_note"])
                    st.dataframe(pd.DataFrame(ex["evidence"]), hide_index=True)

# ── Data quality ──────────────────────────────────────────────────────────────
with tab_dq:
    alerts = get("/quality/alerts")
    if alerts is None:
        st.warning("No DQ report yet. Run `make pipeline`.")
    elif not alerts:
        st.success("No data-quality alerts.")
    else:
        a = pd.DataFrame(alerts)
        st.metric("Alerts", len(a), f"{a['dt'].nunique()} affected days")
        st.bar_chart(a.groupby(["dt", "check"]).size().unstack(fill_value=0))
        st.dataframe(a, use_container_width=True, hide_index=True)

# ── Experiment ────────────────────────────────────────────────────────────────
with tab_exp:
    exp = get("/decision/experiment")
    if exp:
        post = pd.DataFrame(exp["posterior"]).T
        post["message"] = [exp["variants"][k] for k in post.index]
        st.write(f"Settled nudges: **{exp['settled']}** · pending (within 2h window): **{exp['pending']}**")
        st.dataframe(post, use_container_width=True)
        st.caption("Reward = a task completed within 2 hours of the nudge. Thompson sampling shifts traffic to the best variant.")
    if BANDIT_IMG.exists():
        st.image(str(BANDIT_IMG), caption="Offline simulation: bandit vs fixed A/B split", use_column_width=True)
    log = get("/decision/log", limit=30)
    if log:
        st.subheader("Recent decisions")
        st.dataframe(pd.DataFrame(log), use_container_width=True, hide_index=True)

# ── Ask ───────────────────────────────────────────────────────────────────────
with tab_ask:
    q = st.text_input("Ask a question about the warehouse",
                      "Which platform had the highest average night_share in the last 7 days?")
    if st.button("Ask"):
        with st.spinner("Writing and checking SQL..."):
            try:
                out = requests.post(f"{API}/analyst/ask", json={"question": q}, timeout=300).json()
            except Exception as e:
                out = {"ok": False, "error": str(e)}
        if out.get("ok"):
            st.success(out["answer"])
            st.code(out["sql"], language="sql")
            st.dataframe(pd.DataFrame(out["rows"]), use_container_width=True, hide_index=True)
            if len(out["attempts"]) > 1:
                with st.expander(f"Self-corrected after {len(out['attempts']) - 1} failed attempt(s)"):
                    st.json(out["attempts"])
        else:
            st.error(out.get("error"))
