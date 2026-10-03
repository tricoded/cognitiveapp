# frontend/pages/08_Daily_Brief.py

import streamlit as st
import requests
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="Daily Brief — Cognitive",
    page_icon="📰",
    layout="wide"
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def fetch_categories() -> dict:
    try:
        res = requests.get(f"{API_BASE}/news/categories", timeout=5)
        res.raise_for_status()
        return res.json()
    except Exception:
        return {
            "categories": [
                "general", "technology", "law", "philosophy",
                "history", "psychology", "maths", "geography"
            ],
            "descriptions": {}
        }

def fetch_daily_brief(category: str) -> dict | None:
    try:
        res = requests.get(
            f"{API_BASE}/news/daily-brief",
            params={"category": category},
            timeout=30
        )
        res.raise_for_status()
        return res.json()
    except requests.exceptions.Timeout:
        st.error("⏱️ Request timed out. The server may be busy — try again.")
        return None
    except requests.exceptions.ConnectionError:
        st.error("🔌 Cannot connect to the backend. Is it running?")
        return None
    except Exception as e:
        st.error(f"❌ Error fetching news: {e}")
        return None

def fetch_deep_dive(topic: str, category: str) -> dict | None:
    try:
        res = requests.post(
            f"{API_BASE}/news/deep-dive",
            json={"topic": topic, "category": category},
            timeout=30
        )
        res.raise_for_status()
        return res.json()
    except requests.exceptions.Timeout:
        st.error("⏱️ Request timed out.")
        return None
    except requests.exceptions.ConnectionError:
        st.error("🔌 Cannot connect to the backend. Is it running?")
        return None
    except Exception as e:
        st.error(f"❌ Error fetching deep dive: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# Category meta (icons + colors)
# ─────────────────────────────────────────────────────────────────────────────
CATEGORY_META = {
    "general":    {"icon": "🌍", "color": "#4A90D9"},
    "technology": {"icon": "💻", "color": "#7B68EE"},
    "law":        {"icon": "⚖️",  "color": "#E67E22"},
    "philosophy": {"icon": "🧠", "color": "#8E44AD"},
    "history":    {"icon": "📜", "color": "#C0392B"},
    "psychology": {"icon": "💬", "color": "#27AE60"},
    "maths":      {"icon": "📐", "color": "#2980B9"},
    "geography":  {"icon": "🗺️", "color": "#16A085"},
}

# ─────────────────────────────────────────────────────────────────────────────
# Session state defaults
# ─────────────────────────────────────────────────────────────────────────────
if "brief_data"       not in st.session_state:
    st.session_state.brief_data = None
if "brief_category"   not in st.session_state:
    st.session_state.brief_category = "general"
if "deepdive_data"    not in st.session_state:
    st.session_state.deepdive_data = None
if "active_tab"       not in st.session_state:
    st.session_state.active_tab = "news"

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("# 📰 Daily Brief")
st.caption(
    f"🕐 {datetime.now().strftime('%A, %B %d %Y  •  %I:%M %p')}"
)
st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Fetch categories from API
# ─────────────────────────────────────────────────────────────────────────────
cat_data     = fetch_categories()
categories   = cat_data.get("categories", [])
descriptions = cat_data.get("descriptions", {})

# ─────────────────────────────────────────────────────────────────────────────
# Tabs: News Brief | Deep Dive
# ─────────────────────────────────────────────────────────────────────────────
tab_news, tab_dive = st.tabs(["📋 News Brief", "🎓 Deep Dive"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — News Brief
# ══════════════════════════════════════════════════════════════════════════════
with tab_news:

    st.markdown("### Choose a Category")

    # Category pills (buttons in a grid)
    cols = st.columns(4)
    for i, cat in enumerate(categories):
        meta = CATEGORY_META.get(cat, {"icon": "📌", "color": "#888"})
        with cols[i % 4]:
            label = f"{meta['icon']} {cat.capitalize()}"
            if st.button(
                label,
                key=f"cat_btn_{cat}",
                use_container_width=True,
                type="primary" if st.session_state.brief_category == cat else "secondary"
            ):
                st.session_state.brief_category = cat
                st.session_state.brief_data     = None  # force refresh
                st.rerun()

    st.divider()

    # ── Show category description ──
    selected     = st.session_state.brief_category
    meta         = CATEGORY_META.get(selected, {"icon": "📌", "color": "#888"})
    desc         = descriptions.get(selected, "")

    st.markdown(
        f"#### {meta['icon']} {selected.capitalize()} News"
        + (f"  \n*{desc}*" if desc else "")
    )

    # ── Fetch button ──
    col_btn, col_cache = st.columns([2, 5])
    with col_btn:
        fetch_clicked = st.button(
            "🔄 Get Today's Brief",
            type="primary",
            use_container_width=True
        )

    if fetch_clicked or st.session_state.brief_data is None:
        with st.spinner(f"Fetching {selected} news..."):
            st.session_state.brief_data = fetch_daily_brief(selected)

    data = st.session_state.brief_data

    if data:
        # ── Cache indicator ──
        with col_cache:
            if data.get("cached"):
                st.success("⚡ Served from cache (faster)")
            else:
                st.info("🆕 Freshly generated")

        # ── AI Summary card ──
        st.markdown("---")
        st.markdown("#### 🤖 AI Summary")
        st.info(data.get("summary", "No summary available."))

        # ── Articles ──
        articles = data.get("articles", [])

        if articles:
            st.markdown(f"#### 📑 Top Articles *(last fetched: {data.get('generated_at', 'N/A')[:10]})*")

            for i, article in enumerate(articles, 1):
                with st.expander(f"{i}. {article.get('title', 'No title')}"):
                    col_left, col_right = st.columns([4, 1])

                    with col_left:
                        snippet = article.get("snippet", article.get("summary", ""))
                        if snippet:
                            st.write(snippet)
                        published = article.get("published", "")
                        if published:
                            st.caption(f"🗓️ Published: {published}")

                    with col_right:
                        link = article.get("link", "#")
                        if link and link != "#":
                            st.link_button("Read →", link, use_container_width=True)
        else:
            st.warning("No articles found for this category right now.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Deep Dive
# ══════════════════════════════════════════════════════════════════════════════
with tab_dive:

    st.markdown("### 🎓 On-Demand Topic Deep Dive")
    st.caption("Ask Cognitive to explain any topic within a subject area.")

    st.divider()

    col_topic, col_cat = st.columns([3, 2])

    with col_topic:
        topic_input = st.text_input(
            "📝 Topic",
            placeholder="e.g., Stoicism, Quantum Computing, The French Revolution",
            max_chars=120
        )

    with col_cat:
        dive_category = st.selectbox(
            "📚 Category",
            options=categories,
            index=0,
            format_func=lambda c: f"{CATEGORY_META.get(c, {}).get('icon', '📌')} {c.capitalize()}"
        )

    dive_btn = st.button(
        "🚀 Generate Deep Dive",
        type="primary",
        disabled=not topic_input.strip(),
        use_container_width=False
    )

    if dive_btn and topic_input.strip():
        with st.spinner(f"Generating deep dive on *{topic_input}*..."):
            st.session_state.deepdive_data = fetch_deep_dive(
                topic_input.strip(),
                dive_category
            )

    dive = st.session_state.deepdive_data

    if dive:
        st.divider()

        # Header
        dive_meta = CATEGORY_META.get(dive.get("category", "general"), {"icon": "📌"})
        st.markdown(
            f"### {dive_meta['icon']} {dive.get('topic', topic_input)}"
        )
        st.caption(
            f"Category: **{dive.get('category', '').capitalize()}**  •  "
            f"Generated: {dive.get('generated_at', '')[:10]}"
            + ("  •  ⚡ *cached*" if dive.get('cached') else "")
        )

        # Overview card
        st.markdown("#### 📖 Overview")
        st.info(dive.get("overview", "No overview available."))

        # Suggest next dive
        st.markdown("---")
        st.markdown("💡 **Want to go deeper?** Type a related topic above and generate another deep dive.")


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — Quick Jump
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📰 Daily Brief")
    st.markdown("---")

    st.markdown("**📋 News Categories**")
    for cat in categories:
        meta = CATEGORY_META.get(cat, {"icon": "📌"})
        active = "→ " if cat == st.session_state.brief_category else "   "
        st.caption(f"{active}{meta['icon']} {cat.capitalize()}")

    st.markdown("---")
    st.markdown("**💡 Tips**")
    st.caption("• News briefs are cached daily — same speed all day")
    st.caption("• Deep dives are cached per topic — instant on repeat")
    st.caption("• Use Deep Dive for study prep or quick learning")
