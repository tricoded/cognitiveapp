# app/routers/decision.py
"""Real-time decision endpoint for the browser extension + experiment readout."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.decision.bandit import VARIANTS, ThompsonBandit
from app.decision.engine import STRATEGIES, SessionFeatures, decide
from app.decision.store import bandit_history, settle_outcomes
from app.models import AIUsageLog, DecisionLog, Task
from app.personal_cdi import personal_cdi

router = APIRouter(prefix="/decision", tags=["Decision Engine"])

HIGH_PRIORITY = ["High", "Critical", "Overdue"]


class DecisionRequest(BaseModel):
    platform: str
    session_minutes: float
    msgs_in_session: int
    msgs_last_5min: int = 0
    delegation_share: float = 0.0
    reask_share: float = 0.0
    local_hour: Optional[int] = None
    today_total_mins: Optional[float] = None     # extension's own counter, if it has one
    daily_budget_mins: float = 120.0


@router.post("")
def make_decision(req: DecisionRequest, db: Session = Depends(get_db)):
    settle_outcomes(db)

    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    logged_today = db.query(func.coalesce(func.sum(AIUsageLog.duration_mins), 0)).filter(AIUsageLog.used_at >= since).scalar()
    today_total = max(float(logged_today or 0), req.today_total_mins or 0) + req.session_minutes

    open_tasks = db.query(Task).filter(Task.status.in_(["pending", "in_progress"]), Task.priority.in_(HIGH_PRIORITY))
    top_task = open_tasks.order_by(Task.due_date).first()

    cdi = personal_cdi(db, days=7).get("cdi")
    f = SessionFeatures(
        platform=req.platform,
        session_minutes=req.session_minutes,
        msgs_in_session=req.msgs_in_session,
        msgs_last_5min=req.msgs_last_5min,
        delegation_share=req.delegation_share,
        reask_share=req.reask_share,
        local_hour=req.local_hour if req.local_hour is not None else datetime.now().hour,
        today_total_mins=today_total,
        daily_budget_mins=req.daily_budget_mins,
        open_high_priority_tasks=open_tasks.count(),
        cdi=cdi,
    )
    result = decide(f)
    if result["action"] == "allow":
        return {**result, "decision_id": None, "variant": None, "message": None}

    # Recent-nudge cooldown: don't nag more than once per 20 minutes
    recent = db.query(DecisionLog).filter(DecisionLog.decided_at >= datetime.utcnow() - timedelta(minutes=20)).first()
    if recent and result["action"] != "cool_down":
        return {**result, "action": "allow", "suppressed": True, "decision_id": None, "variant": None, "message": None}

    bandit = ThompsonBandit.from_history(bandit_history(db))
    variant = bandit.choose()
    message = VARIANTS[variant].format(
        top_task=top_task.title if top_task else "your most important task",
        ai_mins=int(today_total), cdi=f"{cdi:.0f}" if cdi is not None else "n/a",
    )

    log = DecisionLog(
        platform=req.platform, action=result["action"], variant=variant,
        reasons=result["reasons"], features=f.__dict__,
    )
    db.add(log)
    db.commit()
    return {**result, "decision_id": log.id, "variant": variant, "message": message}


@router.get("/strategies")
def list_strategies():
    return [{"code": s.code, "action": s.action, "desc": s.desc} for s in STRATEGIES]


@router.get("/experiment")
def experiment_readout(db: Session = Depends(get_db)):
    settle_outcomes(db)
    history = bandit_history(db)
    pending = db.query(DecisionLog).filter(DecisionLog.variant.isnot(None), DecisionLog.outcome.is_(None)).count()
    bandit = ThompsonBandit.from_history(history, seed=0)
    return {"variants": VARIANTS, "posterior": bandit.posterior(), "settled": len(history), "pending": pending}


@router.get("/log")
def decision_log(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(DecisionLog).order_by(DecisionLog.decided_at.desc()).limit(limit).all()
    return [
        {"id": r.id, "decided_at": r.decided_at.isoformat(), "platform": r.platform, "action": r.action,
         "variant": r.variant, "reasons": r.reasons, "outcome": r.outcome}
        for r in rows
    ]
