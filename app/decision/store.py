"""Persistence + outcome attribution for the decision engine."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import DecisionLog

OUTCOME_WINDOW = timedelta(hours=2)


def settle_outcomes(db: Session, now: datetime | None = None) -> int:
    """Nudges older than the window with no task completion → outcome 0."""
    now = now or datetime.utcnow()
    stale = db.query(DecisionLog).filter(
        DecisionLog.variant.isnot(None),
        DecisionLog.outcome.is_(None),
        DecisionLog.decided_at < now - OUTCOME_WINDOW,
    ).all()
    for d in stale:
        d.outcome, d.outcome_at = 0, now
    if stale:
        db.commit()
    return len(stale)


def record_task_completion(db: Session, completed_at: datetime | None) -> int:
    """
    Credit every pending nudge shown in the 2h before this completion.
    Called from the task-completion endpoint; never raises (it is a side
    channel and must not break task completion).
    """
    try:
        # Task timestamps are local (datetime.now()); decisions are UTC.
        # Compare in UTC.
        offset = datetime.utcnow() - datetime.now()
        done_utc = (completed_at or datetime.now()) + offset
        pending = db.query(DecisionLog).filter(
            DecisionLog.variant.isnot(None),
            DecisionLog.outcome.is_(None),
            DecisionLog.decided_at >= done_utc - OUTCOME_WINDOW,
            DecisionLog.decided_at <= done_utc,
        ).all()
        for d in pending:
            d.outcome, d.outcome_at = 1, done_utc
        if pending:
            db.commit()
        return len(pending)
    except Exception:
        db.rollback()
        return 0


def bandit_history(db: Session) -> list[tuple[str, int]]:
    rows = db.query(DecisionLog.variant, DecisionLog.outcome).filter(
        DecisionLog.variant.isnot(None), DecisionLog.outcome.isnot(None)
    ).all()
    return [(v, o) for v, o in rows]
