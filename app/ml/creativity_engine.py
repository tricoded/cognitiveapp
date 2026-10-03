# app/ml/creativity_engine.py
"""
Phase C — Creativity & Problem Solving Engine
Personalizes prompt selection based on user engagement history.
Persists to creativity_log.json — zero extra DB tables.
"""

from __future__ import annotations

import json
import random
import logging
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Path constants ─────────────────────────────────────────────────────────────
_ENGINE_DIR   = Path(__file__).resolve().parent          # app/ml/
_PROJECT_ROOT = _ENGINE_DIR.parent.parent                # cognitive/
_DATA_DIR     = _PROJECT_ROOT / "data"

PROMPTS_FILE  = _DATA_DIR / "prompts.json"
LOG_FILE      = _DATA_DIR / "creativity_log.json"

# ── Fallback in case data/ folder doesn't exist yet ───────────────────────────
_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  FILE I/O
# ══════════════════════════════════════════════════════════════════════════════

def load_prompts() -> list[dict]:
    """Load all prompts from data/prompts.json."""
    # Try data/prompts.json first, then project root fallback
    for candidate in [PROMPTS_FILE, _PROJECT_ROOT / "prompts.json"]:
        if candidate.exists():
            try:
                with open(candidate, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Failed to load prompts from %s: %s", candidate, e)
                return []
    logger.warning("prompts.json not found. Checked: %s", PROMPTS_FILE)
    return []


def load_log() -> dict:
    """Load the creativity log. Returns empty structure if missing."""
    if not LOG_FILE.exists():
        return {"entries": [], "category_scores": {}}
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            data = json.load(f)
            # Ensure expected keys exist (safe migration)
            data.setdefault("entries", [])
            data.setdefault("category_scores", {})
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load creativity log: %s", e)
        return {"entries": [], "category_scores": {}}


def save_log(log: dict) -> None:
    """Persist the creativity log to disk."""
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2, default=str)
    except OSError as e:
        logger.error("Failed to save creativity log: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
#  PROMPT SELECTION  (personalised)
# ══════════════════════════════════════════════════════════════════════════════

def _build_weights(prompts: list[dict], log: dict) -> list[float]:
    """
    Compute a selection weight for every prompt.

    Rules:
    - Already completed today → 0  (never repeat same day)
    - Completed before but highly rated → slight bonus
    - User's favourite categories → higher weight
    - Least-seen categories → small discovery bonus
    """
    today          = date.today().isoformat()
    category_scores: dict[str, float] = log.get("category_scores", {})

    # Track which prompt IDs were done today
    done_today_ids: set[str] = {
        e["prompt_id"]
        for e in log.get("entries", [])
        if e.get("date") == today and e.get("completed")
    }

    # Category completion counts (for discovery bonus)
    cat_counts: Counter = Counter(
        e.get("category", "")
        for e in log.get("entries", [])
        if e.get("completed")
    )

    weights: list[float] = []
    for p in prompts:
        pid = p.get("id", "")
        cat = p.get("category", "")

        # Hard exclude: already done today
        if pid in done_today_ids:
            weights.append(0.0)
            continue

        # Base weight
        w = 1.0

        # Category preference bonus (normalised 0–2)
        cat_score = category_scores.get(cat, 0.5)   # default 0.5 = neutral
        w += cat_score * 2.0

        # Discovery bonus: rarer categories get a small lift
        seen = cat_counts.get(cat, 0)
        if seen == 0:
            w += 0.8
        elif seen < 3:
            w += 0.3

        weights.append(max(w, 0.01))   # never fully zero for unseens

    return weights


def get_todays_prompt() -> Optional[dict]:
    """
    Return the prompt chosen for today.

    - Deterministic within the same day (seeds by date hash).
    - Personalises selection by category weights built from history.
    - Returns None if no prompts are available.
    """
    prompts = load_prompts()
    if not prompts:
        logger.warning("No prompts loaded — cannot select today's prompt.")
        return None

    log = load_log()

    # If today's prompt is already recorded, return the same one
    today = date.today().isoformat()
    for entry in reversed(log.get("entries", [])):
        if entry.get("date") == today and entry.get("prompt_id"):
            pid    = entry["prompt_id"]
            prompt = next((p for p in prompts if p.get("id") == pid), None)
            if prompt:
                return prompt

    # Pick a new prompt with personalised weights
    weights = _build_weights(prompts, log)
    total   = sum(weights)
    if total == 0:
        # All prompts already done today — pick random as fallback
        return random.choice(prompts)

    # Weighted random selection seeded by date (consistent for the day)
    import hashlib
    seed = int(hashlib.md5(today.encode()).hexdigest(), 16)
    rng  = random.Random(seed)

    cumulative, dart = 0.0, rng.uniform(0, total)
    for prompt, w in zip(prompts, weights):
        cumulative += w
        if dart <= cumulative:
            # Record that this prompt was assigned today (not yet completed)
            log["entries"].append({
                "prompt_id": prompt["id"],
                "category":  prompt.get("category", ""),
                "date":      today,
                "completed": False,
                "response":  None,
                "rating":    None,
                "time_spent": None,
                "assigned_at": datetime.utcnow().isoformat(),
            })
            save_log(log)
            return prompt

    return prompts[0]   # final safety fallback


# ══════════════════════════════════════════════════════════════════════════════
#  SUBMISSION
# ══════════════════════════════════════════════════════════════════════════════

def submit_response(
    prompt_id:  str,
    response:   str,
    rating:     int,
    time_spent: int,
) -> dict:
    """
    Mark today's prompt as completed and update category preference scores.

    Category scores are Exponential Moving Averages so recent ratings matter
    more than old ones.  Score is normalised to [0, 1].

    Returns: { "streak": int, "category_scores": dict }
    """
    log   = load_log()
    today = date.today().isoformat()

    # Normalise rating to [0, 1]
    rating_norm = (rating - 1) / 4.0   # rating 1–5 → 0.0–1.0

    # Find today's assigned entry and mark complete
    updated = False
    for entry in reversed(log["entries"]):
        if entry.get("prompt_id") == prompt_id and entry.get("date") == today:
            entry["completed"]   = True
            entry["response"]    = response
            entry["rating"]      = rating
            entry["time_spent"]  = time_spent
            entry["completed_at"] = datetime.utcnow().isoformat()
            category = entry.get("category", "")
            updated = True
            break

    if not updated:
        # Edge case: entry was never pre-assigned (e.g. custom run)
        prompts  = load_prompts()
        prompt   = next((p for p in prompts if p.get("id") == prompt_id), {})
        category = prompt.get("category", "")
        log["entries"].append({
            "prompt_id":    prompt_id,
            "category":     category,
            "date":         today,
            "completed":    True,
            "response":     response,
            "rating":       rating,
            "time_spent":   time_spent,
            "assigned_at":  datetime.utcnow().isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
        })

    # ── Update category EMA score ──────────────────────────────────────────────
    alpha   = 0.3   # EMA smoothing factor — higher = faster adaptation
    scores  = log.get("category_scores", {})
    current = scores.get(category, 0.5)
    scores[category]         = round(current * (1 - alpha) + rating_norm * alpha, 4)
    log["category_scores"]   = scores

    save_log(log)

    return {
        "streak":          get_streak(),
        "category_scores": scores,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  STATE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def has_completed_today() -> bool:
    """Return True if the user already submitted a response today."""
    today = date.today().isoformat()
    log   = load_log()
    return any(
        e.get("date") == today and e.get("completed")
        for e in log.get("entries", [])
    )


def get_streak() -> int:
    """
    Calculate current consecutive daily completion streak.

    Walks backwards from today. A day counts if at least one
    entry is marked completed on that date.
    """
    log = load_log()
    completed_dates: set[str] = {
        e["date"]
        for e in log.get("entries", [])
        if e.get("completed") and e.get("date")
    }

    streak  = 0
    check   = date.today()

    while check.isoformat() in completed_dates:
        streak += 1
        check  -= timedelta(days=1)

    return streak


# ══════════════════════════════════════════════════════════════════════════════
#  ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

def get_creativity_stats() -> dict:
    """
    Return aggregated stats for display in the Creative page header.

    Keys returned:
        total_completed   int
        avg_rating        float | None
        total_time_mins   int
        favorite_category str | None
        category_scores   dict[str, float]   (raw EMA scores)
        by_category       dict[str, int]     (completion counts)
        recent_7_days     list[str]          (dates with completions)
    """
    log     = load_log()
    entries = [e for e in log.get("entries", []) if e.get("completed")]

    if not entries:
        return {
            "total_completed":   0,
            "avg_rating":        None,
            "total_time_mins":   0,
            "favorite_category": None,
            "category_scores":   log.get("category_scores", {}),
            "by_category":       {},
            "recent_7_days":     [],
        }

    ratings    = [e["rating"]     for e in entries if e.get("rating") is not None]
    times      = [e["time_spent"] for e in entries if e.get("time_spent") is not None]
    categories = [e["category"]   for e in entries if e.get("category")]

    cat_counter = Counter(categories)
    fav_cat     = cat_counter.most_common(1)[0][0] if cat_counter else None

    # Last 7 unique completion dates
    today      = date.today()
    recent     = sorted(
        {
            e["date"] for e in entries
            if e.get("date") and
            (today - date.fromisoformat(e["date"])).days <= 7
        },
        reverse=True,
    )

    return {
        "total_completed":   len(entries),
        "avg_rating":        round(sum(ratings) / len(ratings), 2) if ratings else None,
        "total_time_mins":   sum(times),
        "favorite_category": fav_cat,
        "category_scores":   log.get("category_scores", {}),
        "by_category":       dict(cat_counter),
        "recent_7_days":     recent,
    }
