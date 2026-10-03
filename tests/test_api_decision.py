"""API tests for event ingest + decision engine, on an in-memory SQLite DB."""

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.decision.store import record_task_completion
from app.models import DecisionLog
from app.routers import ai_usage, decision


@pytest.fixture()
def client_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(ai_usage.router)
    app.include_router(decision.router)
    app.dependency_overrides[get_db] = override
    return TestClient(app), Session


def ev(i, **kw):
    return {"event_id": f"e{i}", "platform": "ChatGPT", "msg_len": 50, "prompt_kind": "delegation", **kw}


def test_event_ingest_is_idempotent(client_db):
    client, _ = client_db
    r1 = client.post("/ai-usage/events", json=[ev(1), ev(2)]).json()
    r2 = client.post("/ai-usage/events", json=[ev(2), ev(3), ev(3)]).json()   # retry + dup inside batch
    assert r1 == {"accepted": 2, "duplicates": 0}
    assert r2 == {"accepted": 1, "duplicates": 2}


def test_normal_session_is_allowed_and_not_logged(client_db):
    client, Session = client_db
    out = client.post("/decision", json={"platform": "ChatGPT", "session_minutes": 5, "msgs_in_session": 3}).json()
    assert out["action"] == "allow"
    assert Session().query(DecisionLog).count() == 0


def test_nudge_is_logged_with_variant_and_credited_on_task_completion(client_db):
    client, Session = client_db
    out = client.post("/decision", json={
        "platform": "ChatGPT", "session_minutes": 50, "msgs_in_session": 30, "reask_share": 0.5, "local_hour": 2,
    }).json()
    assert out["action"] == "hard_nudge"
    assert {"S02_DOOM_PROMPTING", "S03_LATE_NIGHT_BINGE"} <= set(out["reasons"])
    assert out["variant"] and out["message"]

    # second call inside the 20-min cooldown is suppressed
    again = client.post("/decision", json={"platform": "ChatGPT", "session_minutes": 55, "msgs_in_session": 35,
                                           "reask_share": 0.5, "local_hour": 2}).json()
    assert again["action"] == "allow" and again.get("suppressed")

    db = Session()
    assert record_task_completion(db, datetime.now()) == 1
    assert db.query(DecisionLog).one().outcome == 1

    exp = client.get("/decision/experiment").json()
    assert exp["settled"] == 1
    assert exp["posterior"][out["variant"]]["successes"] == 1


def test_stale_nudge_settles_as_failure(client_db):
    client, Session = client_db
    db = Session()
    db.add(DecisionLog(action="soft_nudge", variant="reflect", reasons=[], features={},
                       decided_at=datetime.utcnow() - timedelta(hours=3)))
    db.commit()
    exp = client.get("/decision/experiment").json()
    assert exp["settled"] == 1 and exp["posterior"]["reflect"]["successes"] == 0
