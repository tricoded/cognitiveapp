"""Text-to-SQL agent loop with a scripted fake LLM: guard rejection → self-correction → answer."""

import pandas as pd
import pytest

from app.analyst import sql_agent, warehouse


@pytest.fixture()
def tiny_warehouse(tmp_path, monkeypatch):
    for dt, rows in {"2026-07-29": [("u1", 0.2), ("u2", 0.4)], "2026-07-30": [("u1", 0.9), ("u2", 0.1)]}.items():
        d = tmp_path / "warehouse" / "ads_user_risk_score_1d" / f"dt={dt}"
        d.mkdir(parents=True)
        pd.DataFrame(rows, columns=["user_id", "risk_score"]).to_parquet(d / "p.parquet")
    monkeypatch.setattr(warehouse, "WAREHOUSE", tmp_path / "warehouse")
    monkeypatch.setattr(warehouse, "_con", None)
    monkeypatch.setattr(warehouse, "_signature", None)


def scripted(replies):
    calls = []

    def fake_chat(messages, **kw):
        calls.append(messages)
        return replies.pop(0)
    return fake_chat, calls


def test_self_corrects_after_guard_rejection(tiny_warehouse, monkeypatch):
    fake, calls = scripted([
        "```sql\nSELECT * FROM read_parquet('/etc/passwd')\n```",                       # rejected by guard
        "```sql\nSELECT user_id, risk_score FROM ads_user_risk_score_1d "
        "WHERE dt = (SELECT MAX(dt) FROM ads_user_risk_score_1d) ORDER BY risk_score DESC\n```",
        "u1 has the highest risk score (0.9) on 2026-07-30.",                           # summary
    ])
    monkeypatch.setattr(sql_agent, "_chat", fake)
    out = sql_agent.ask("who is riskiest today?")
    assert out["ok"]
    assert out["rows"][0] == {"user_id": "u1", "risk_score": 0.9}
    assert "LIMIT 200" in out["sql"]
    assert len(out["attempts"]) == 2 and "table functions" in out["attempts"][0]["error"]
    # the guard error was fed back to the model
    assert "failed" in calls[1][-1]["content"]


def test_gives_up_after_max_attempts(tiny_warehouse, monkeypatch):
    fake, _ = scripted(["DROP TABLE ads_user_risk_score_1d"] * sql_agent.MAX_ATTEMPTS)
    monkeypatch.setattr(sql_agent, "_chat", fake)
    out = sql_agent.ask("delete everything")
    assert not out["ok"] and len(out["attempts"]) == sql_agent.MAX_ATTEMPTS


def test_extract_sql():
    assert sql_agent.extract_sql("Here:\n```sql\nSELECT 1;\n```") == "SELECT 1"
    assert sql_agent.extract_sql("SELECT 2") == "SELECT 2"
