# app/personal_cdi.py
"""
Cognitive Dependency Index for the *real* user, computed from the events the
extension sends (ai_usage_events) plus task history in SQLite.

Same components and weights as the warehouse version
(pipeline/spark/sql/ads_user_cdi_1d.sql). With a population of one, the
"intensity" component can't be a percentile, so it is AI minutes vs budget.
"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AIUsageEvent, AIUsageLog, Task

WEIGHTS = {"delegation": 0.35, "reask": 0.25, "night": 0.15, "intensity": 0.25}


def personal_cdi(db: Session, days: int = 7, daily_budget_mins: float = 120.0) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    ev = db.query(AIUsageEvent).filter(AIUsageEvent.event_ts >= since).all()
    ai_mins = db.query(func.coalesce(func.sum(AIUsageLog.duration_mins), 0)).filter(AIUsageLog.used_at >= since).scalar() or 0
    done = db.query(Task).filter(Task.status == "completed", Task.completed_at >= datetime.now() - timedelta(days=days)).count()

    if not ev:
        return {"cdi": None, "events": 0, "ai_minutes": int(ai_mins), "tasks_completed": done,
                "message": "No prompt-level events yet. Install/update the extension to start collecting features."}

    n = len(ev)
    delegation = sum(e.prompt_kind == "delegation" for e in ev) / n
    reask = sum(bool(e.is_reask) for e in ev) / n
    night = sum(0 <= ((e.event_ts.hour + (e.tz_offset or 0)) % 24) <= 5 for e in ev) / n
    comp = {
        "delegation": round(delegation, 3),
        "reask": round(min(1.0, reask / 0.30), 3),
        "night": round(min(1.0, night / 0.50), 3),
        "intensity": round(min(1.0, ai_mins / (days * daily_budget_mins)), 3),
    }
    cdi = round(100 * sum(WEIGHTS[k] * v for k, v in comp.items()), 1)
    return {
        "cdi": cdi,
        "band": "high" if cdi >= 60 else "medium" if cdi >= 40 else "low",
        "components": comp,
        "weights": WEIGHTS,
        "events": n,
        "ai_minutes": int(ai_mins),
        "tasks_completed": done,
        "ai_minutes_per_completed_task": round(ai_mins / done, 1) if done else None,
        "window_days": days,
    }
