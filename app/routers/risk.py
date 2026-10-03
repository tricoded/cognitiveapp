# app/routers/risk.py
"""Serving layer for the offline warehouse: risk scores, DQ alerts, model card, analyst agent."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analyst import sql_agent, warehouse
from app.database import get_db
from app.personal_cdi import personal_cdi

router = APIRouter(tags=["Risk & Data"])


def _require_warehouse():
    if not warehouse.available():
        raise HTTPException(503, "Warehouse not built. Run `make all` (see README).")


@router.get("/risk/users")
def top_risky_users(top: int = 50, dt: Optional[str] = None):
    _require_warehouse()
    return warehouse.query(
        """SELECT user_id, dt, risk_score, risk_rank_pct, rule_score, rule_reasons, reason_1, reason_2, reason_3
           FROM ads_user_risk_score_1d
           WHERE dt = COALESCE(?, (SELECT MAX(dt) FROM ads_user_risk_score_1d))
           ORDER BY risk_score DESC LIMIT ?""",
        [dt, min(top, 500)],
    )


@router.get("/risk/users/{user_id}/explain")
def explain_user(user_id: str, dt: Optional[str] = None):
    _require_warehouse()
    out = sql_agent.explain_user(user_id, dt)
    if not out["ok"]:
        raise HTTPException(404, out["error"])
    return out


@router.get("/risk/score-distribution")
def score_distribution(dt: Optional[str] = None, bins: int = 20):
    _require_warehouse()
    return warehouse.query(
        """SELECT LEAST(CAST(FLOOR(risk_score * ?) AS INTEGER), ? - 1) AS bin, COUNT(*) AS users
           FROM ads_user_risk_score_1d
           WHERE dt = COALESCE(?, (SELECT MAX(dt) FROM ads_user_risk_score_1d))
           GROUP BY 1 ORDER BY 1""",
        [bins, bins, dt],
    )


@router.get("/risk/model")
def model_card():
    p = warehouse.ROOT / "reports" / "model_metrics.json"
    if not p.exists():
        raise HTTPException(503, "No trained model. Run `make train`.")
    return json.loads(p.read_text())


@router.get("/quality/alerts")
def dq_alerts(dt: Optional[str] = None):
    p = warehouse.ROOT / "reports" / "dq_alerts.json"
    if not p.exists():
        raise HTTPException(503, "No DQ report. Run `make pipeline`.")
    alerts = json.loads(p.read_text())
    return [a for a in alerts if dt is None or a["dt"] == dt]


class AskRequest(BaseModel):
    question: str


@router.post("/analyst/ask")
def ask_analyst(req: AskRequest):
    return sql_agent.ask(req.question)


@router.get("/cdi/me")
def my_cdi(days: int = 7, db: Session = Depends(get_db)):
    return personal_cdi(db, days=days)
