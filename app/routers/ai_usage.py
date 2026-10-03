# app/routers/ai_usage.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.models import AIUsageEvent, AIUsageLog

router = APIRouter(prefix="/ai-usage", tags=["AI Usage"])


class AIUsageCreate(BaseModel):
    tool_name:     str
    category:      str
    duration_mins: int
    quality:       str = "active"
    notes:         Optional[str] = None


@router.post("/", status_code=201)
def create_log(data: AIUsageCreate, db: Session = Depends(get_db)):
    log = AIUsageLog(
        tool_name=data.tool_name,
        category=data.category,
        duration_mins=data.duration_mins,
        quality=data.quality,
        notes=data.notes,
        used_at=datetime.utcnow()  # ← EXPLICITLY SET THIS
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.get("/")
def get_logs(
    days:     int = 30,
    category: Optional[str] = None,
    db:       Session = Depends(get_db)
):
    since = datetime.utcnow() - timedelta(days=days)
    q     = db.query(AIUsageLog).filter(AIUsageLog.used_at >= since)
    if category:
        q = q.filter(AIUsageLog.category == category)
    return q.order_by(AIUsageLog.used_at.desc()).all()


@router.get("/today")
def get_today(db: Session = Depends(get_db)):
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    logs  = db.query(AIUsageLog).filter(AIUsageLog.used_at >= start).all()
    total = sum(l.duration_mins for l in logs)
    ai_budget = 120

    return {
        "logs":        [
            {
                "id":            l.id,
                "tool_name":     l.tool_name,
                "category":      l.category,
                "duration_mins": l.duration_mins,
                "quality":       l.quality,
                "notes":         l.notes,
                "used_at":       l.used_at.isoformat() if l.used_at else None,
            }
            for l in logs
        ],
        "total_mins":  total,
        "budget_mins": ai_budget,
        "pct_used":    round(min(total / ai_budget, 1.0) * 100, 1),
        "over_budget": total > ai_budget,
    }


@router.get("/stats")
def get_stats(days: int = 7, db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(days=days)
    logs  = db.query(AIUsageLog).filter(AIUsageLog.used_at >= since).all()

    if not logs:
        return {"message": "No data yet", "days": days}

    by_day:  dict[str, int] = {}
    by_cat:  dict[str, int] = {}
    by_tool: dict[str, int] = {}

    for l in logs:
        d = l.used_at.strftime("%a %d") if l.used_at else "?"
        by_day[d]        = by_day.get(d, 0)        + l.duration_mins
        by_cat[l.category]  = by_cat.get(l.category, 0)  + l.duration_mins
        by_tool[l.tool_name] = by_tool.get(l.tool_name, 0) + l.duration_mins

    active  = sum(l.duration_mins for l in logs if l.quality == "active")
    passive = sum(l.duration_mins for l in logs if l.quality == "passive")
    total   = sum(l.duration_mins for l in logs)

    return {
        "total_mins":       total,
        "by_day":           by_day,
        "by_category":      by_cat,
        "by_tool":          by_tool,
        "active_mins":      active,
        "passive_mins":     passive,
        "active_pct":       round(active / total * 100, 1) if total else 0,
        "session_count":    len(logs),
        "avg_session_mins": round(total / len(logs), 1) if logs else 0,
    }


@router.delete("/{log_id}")
def delete_log(log_id: int, db: Session = Depends(get_db)):
    log = db.query(AIUsageLog).filter(AIUsageLog.id == log_id).first()
    if not log:
        raise HTTPException(404, "Log not found")
    db.delete(log)
    db.commit()
    return {"message": f"Log {log_id} deleted"} 

# ── Prompt-level events (on-device features only, no prompt text) ─────────────

class AIUsageEventIn(BaseModel):
    event_id:    str
    platform:    str
    client_ts:   Optional[datetime] = None
    tz_offset:   int = 0
    device_id:   Optional[str] = None
    session_id:  Optional[str] = None
    msg_len:     Optional[int] = None
    has_code:    bool = False
    is_question: bool = False
    is_reask:    bool = False
    prompt_kind: Optional[str] = None
    app_version: Optional[str] = None


@router.post("/events", status_code=202)
def ingest_events(events: list[AIUsageEventIn], db: Session = Depends(get_db)):
    """
    Batch ingest from the extension. Idempotent on event_id: the extension
    retries failed batches, and a retry must not double-count (this exact bug
    is one of the incidents the warehouse DQ layer detects).
    """
    if len(events) > 500:
        raise HTTPException(413, "max 500 events per batch")
    ids = [e.event_id for e in events]
    existing = {r[0] for r in db.query(AIUsageEvent.event_id).filter(AIUsageEvent.event_id.in_(ids)).all()}
    now = datetime.utcnow()
    new = []
    for e in events:
        if e.event_id in existing:
            continue
        existing.add(e.event_id)
        new.append(AIUsageEvent(
            event_id=e.event_id, platform=e.platform, event_ts=now,
            client_ts=e.client_ts.replace(tzinfo=None) if e.client_ts else None,
            tz_offset=e.tz_offset, device_id=e.device_id, session_id=e.session_id, msg_len=e.msg_len,
            has_code=int(e.has_code), is_question=int(e.is_question), is_reask=int(e.is_reask),
            prompt_kind=e.prompt_kind, app_version=e.app_version,
        ))
    db.add_all(new)
    db.commit()
    return {"accepted": len(new), "duplicates": len(events) - len(new)}
