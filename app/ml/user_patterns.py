# app/ml/user_patterns.py
"""
Personalization Engine — Phase A
Analyzes completed task history to extract behavioral patterns.
Saves/loads from user_patterns.json for persistence.
Zero extra DB tables required.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session
from app.models import Task

logger     = logging.getLogger(__name__)
PFILE      = Path(__file__).parent.parent.parent / "user_patterns.json"
EMPTY      = {}


# ══════════════════════════════════════════════════════════════════════════════
#  SAVE / LOAD
# ══════════════════════════════════════════════════════════════════════════════

def _save(data: dict) -> None:
    try:
        with open(PFILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"[Patterns] Save failed: {e}")


def _load() -> dict:
    try:
        if PFILE.exists():
            with open(PFILE) as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[Patterns] Load failed: {e}")
    return {}


# ══════════════════════════════════════════════════════════════════════════════
#  CORE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_user_patterns(db: Session, user_id: int = 0) -> dict:
    """
    Full pattern analysis from completed task history.
    Returns dict of insights — also persists to JSON.
    Called on: greeting, plan, and after every task completion.
    """
    completed = (
        db.query(Task)
        .filter(Task.status.in_(["completed", "archived"]))
        .all()
    )

    if len(completed) < 3:
        # Not enough data yet — return what we know
        cached = _load()
        cached["has_enough_data"] = False
        cached["completed_count"] = len(completed)
        return cached

    patterns: dict = {
        "has_enough_data":  True,
        "completed_count":  len(completed),
        "last_updated":     datetime.now().isoformat(),
    }

    # ── 1. Peak productivity hour ─────────────────────────────────────────
    completion_hours = []
    for t in completed:
        if t.completed_at:
            completion_hours.append(t.completed_at.hour)

    if completion_hours:
        hour_counts = Counter(completion_hours)
        peak_hour   = hour_counts.most_common(1)[0][0]
        patterns["peak_hour"]       = peak_hour
        patterns["hour_distribution"] = dict(sorted(hour_counts.items()))

    # ── 2. Most productive weekday ─────────────────────────────────────────
    completion_days = []
    for t in completed:
        if t.completed_at:
            completion_days.append(t.completed_at.weekday())  # 0=Mon, 6=Sun

    if completion_days:
        day_names   = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        day_counts  = Counter(completion_days)
        best_day_i  = day_counts.most_common(1)[0][0]
        patterns["best_day"]              = day_names[best_day_i]
        patterns["best_day_index"]        = best_day_i
        patterns["day_distribution"]      = {
            day_names[k]: v for k, v in sorted(day_counts.items())
        }

    # ── 3. Estimate accuracy (over/under estimator) ────────────────────────
    estimable = [
        t for t in completed
        if t.estimated_minutes and t.actual_minutes and t.actual_minutes > 0
    ]
    if len(estimable) >= 3:
        errors    = [t.actual_minutes - t.estimated_minutes for t in estimable]
        avg_error = sum(errors) / len(errors)
        mae       = sum(abs(e) for e in errors) / len(errors)

        patterns["avg_estimate_error_min"] = round(avg_error, 1)
        patterns["mae_minutes"]            = round(mae, 1)
        patterns["tends_to"]               = (
            "overestimate" if avg_error < -5
            else "underestimate" if avg_error > 5
            else "estimate accurately"
        )
        # Correction factor for plan scheduler
        patterns["estimate_correction_factor"] = round(
            1 + (avg_error / max(
                sum(t.estimated_minutes for t in estimable) / len(estimable), 1
            )), 3
        )

    # ── 4. Favorite categories (by completion count) ──────────────────────
    cat_counts  = Counter(t.category or "Work" for t in completed)
    cat_time    = defaultdict(int)
    for t in completed:
        cat_time[t.category or "Work"] += t.actual_minutes or t.estimated_minutes or 0

    patterns["category_counts"]    = dict(cat_counts.most_common())
    patterns["category_time_mins"] = dict(
        sorted(cat_time.items(), key=lambda x: -x[1])
    )
    patterns["top_category"]       = cat_counts.most_common(1)[0][0] if cat_counts else "Work"
    patterns["top_time_category"]  = (
        max(cat_time, key=cat_time.get) if cat_time else "Work"
    )

    # ── 5. Average session length ─────────────────────────────────────────
    timed_tasks = [t for t in completed if t.actual_minutes]
    if timed_tasks:
        avg_mins = sum(t.actual_minutes for t in timed_tasks) / len(timed_tasks)
        patterns["avg_task_duration_mins"] = round(avg_mins, 1)

    # ── 6. Completion velocity (tasks/day over last 14 days) ──────────────
    two_weeks_ago = datetime.now() - timedelta(days=14)
    recent        = [
        t for t in completed
        if t.completed_at and t.completed_at >= two_weeks_ago
    ]
    if recent:
        days_with_completions = len(set(
            t.completed_at.date() for t in recent if t.completed_at
        ))
        patterns["recent_velocity"]       = round(len(recent) / 14, 2)
        patterns["active_days_last_14"]   = days_with_completions
        patterns["recent_completed_count"] = len(recent)

    # ── 7. Priority preference (what priority do they actually complete?) ──
    pri_counts = Counter(t.priority or "Medium" for t in completed)
    patterns["completed_by_priority"] = dict(pri_counts.most_common())

    # ── 8. Procrastination score ──────────────────────────────────────────
    #  = avg days between task creation and completion
    completion_delays = []
    for t in completed:
        if t.created_at and t.completed_at:
            delay = (t.completed_at - t.created_at).total_seconds() / 3600  # hours
            completion_delays.append(delay)

    if completion_delays:
        avg_delay = sum(completion_delays) / len(completion_delays)
        patterns["avg_completion_delay_hours"] = round(avg_delay, 1)
        patterns["procrastination_score"] = (
            "low"    if avg_delay < 24
            else "medium" if avg_delay < 72
            else "high"
        )

    # ── 9. Preferred task duration ────────────────────────────────────────
    duration_buckets = {"quick (≤30min)": 0, "medium (31-90min)": 0, "long (90min+)": 0}
    for t in completed:
        mins = t.actual_minutes or t.estimated_minutes or 60
        if mins <= 30:
            duration_buckets["quick (≤30min)"] += 1
        elif mins <= 90:
            duration_buckets["medium (31-90min)"] += 1
        else:
            duration_buckets["long (90min+)"] += 1
    patterns["duration_preference"] = max(duration_buckets, key=duration_buckets.get)
    patterns["duration_breakdown"]  = duration_buckets

    _save(patterns)
    logger.info(f"[Patterns] Updated — {len(completed)} tasks analyzed")
    return patterns


# ══════════════════════════════════════════════════════════════════════════════
#  PERSONALIZED PLAN ADJUSTER
# ══════════════════════════════════════════════════════════════════════════════

def adjust_plan_for_user(tasks: list, patterns: dict) -> list:
    """
    Reorders + adjusts estimated times based on user patterns.
    Call this inside handle_get_plan() before rendering.
    """
    if not patterns.get("has_enough_data"):
        return tasks  # not enough data yet — return as-is

    now          = datetime.now()
    peak_hour    = patterns.get("peak_hour")
    correction   = patterns.get("estimate_correction_factor", 1.0)
    pri_order    = {"Overdue": 0, "Critical": 1, "High": 2, "Medium": 3, "Low": 4}

    # Apply estimate correction
    if correction and correction != 1.0:
        for t in tasks:
            if t.estimated_minutes:
                corrected = int(t.estimated_minutes * correction)
                # Cap between 5min and 480min
                t._adjusted_estimate = max(5, min(corrected, 480))
            else:
                t._adjusted_estimate = 60

    # If currently near peak hour, surface most important tasks
    is_peak = peak_hour and abs(now.hour - peak_hour) <= 1
    if is_peak:
        # Sort: critical/high first during peak hours
        tasks.sort(key=lambda t: pri_order.get(
            t.priority or "Medium", 99
        ))
    else:
        # Off-peak: surface quick wins + low-priority to preserve peak energy
        def off_peak_sort(t):
            pri_score = pri_order.get(t.priority or "Medium", 99)
            dur_score = (t.estimated_minutes or 60) / 60  # prefer shorter off-peak
            return (pri_score * 0.6) + (dur_score * 0.4)

        tasks.sort(key=off_peak_sort)

    return tasks


# ══════════════════════════════════════════════════════════════════════════════
#  PERSONALIZED INSIGHT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def get_personalized_insights(patterns: dict) -> list[str]:
    """
    Returns a list of human-readable insight strings.
    Used in greeting, stats, and plan pages.
    """
    insights = []

    if not patterns.get("has_enough_data"):
        count = patterns.get("completed_count", 0)
        remaining = 3 - count
        insights.append(
            f"🌱 Complete {remaining} more task(s) to unlock personalized insights!"
        )
        return insights

    # Peak hour
    if "peak_hour" in patterns:
        h = patterns["peak_hour"]
        suffix = "AM" if h < 12 else "PM"
        display_h = h if h <= 12 else h - 12
        insights.append(
            f"⚡ Your peak focus is around {display_h}:00 {suffix} — "
            f"schedule your hardest tasks then."
        )

    # Best day
    if "best_day" in patterns:
        insights.append(
            f"📅 Your most productive day is {patterns['best_day']}."
        )

    # Estimate accuracy
    if "tends_to" in patterns:
        err = patterns.get("avg_estimate_error_min", 0)
        direction = patterns["tends_to"]
        if direction != "estimate accurately":
            insights.append(
                f"🎯 You tend to {direction} tasks by ~{abs(err):.0f}min — "
                f"I've adjusted your time estimates."
            )
        else:
            insights.append("🎯 Your time estimates are pretty accurate — nice!")

    # Top category
    if "top_category" in patterns:
        insights.append(
            f"📁 You get the most done in {patterns['top_category']}."
        )

    # Procrastination score
    score = patterns.get("procrastination_score")
    delay = patterns.get("avg_completion_delay_hours", 0)
    if score == "high":
        insights.append(
            f"😬 Tasks take ~{delay:.0f}h from creation to completion on average. "
            f"Try the 2-minute rule for small tasks!"
        )
    elif score == "low":
        insights.append("🚀 You complete tasks quickly — low procrastination score!")

    # Velocity
    velocity = patterns.get("recent_velocity")
    if velocity:
        insights.append(
            f"📈 You've been completing ~{velocity:.1f} tasks/day over the last 2 weeks."
        )

    return insights


# ══════════════════════════════════════════════════════════════════════════════
#  QUICK CACHED READ (for handlers that need speed)
# ══════════════════════════════════════════════════════════════════════════════

def get_cached_patterns() -> dict:
    """
    Fast read from JSON — no DB query.
    Use in greeting/plan handlers where speed matters.
    """
    return _load()
