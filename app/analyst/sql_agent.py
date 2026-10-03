"""
LLM data-analyst agent: natural-language question → guarded SQL → answer.

Loop (at most MAX_ATTEMPTS):
  1. LLM writes one DuckDB SELECT, given the warehouse schema
  2. sql_guard validates it (allowlist, SELECT-only, LIMIT, no file access)
  3. run it; if validation or execution fails, feed the error back and retry
  4. LLM summarises the rows in 1–3 sentences, citing numbers

Also: explain_user(): turn a flagged user's risk score + top SHAP reasons into
a short analyst-style case note.
"""

from __future__ import annotations

import logging
import os
import re

import httpx

from app.analyst import warehouse
from app.analyst.sql_guard import UnsafeSQL, validate

logger = logging.getLogger(__name__)

_host = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_BASE_URL = _host if _host.startswith("http") else f"http://{_host}:{os.getenv('OLLAMA_PORT', '11434')}"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
MAX_ATTEMPTS = 3

SQL_SYSTEM = """You are a senior data analyst. Write ONE DuckDB SQL SELECT query that answers the question.
Rules:
- Use only the tables and columns listed below. Never invent columns.
- dt is a string 'YYYY-MM-DD'. For "latest"/"today" use (SELECT MAX(dt) FROM <table>).
- Shares are 0-1 fractions. Round results to 3 decimals.
- Return only the SQL inside a ```sql code block, nothing else.

Schema:
{schema}
"""

SUMMARY_SYSTEM = """You are a data analyst. Answer the user's question in 1-3 plain sentences using ONLY the
query result below. Quote concrete numbers. If the result is empty, say so. No markdown."""


def _chat(messages: list[dict], temperature: float = 0.1, max_tokens: int = 400) -> str:
    with httpx.Client(timeout=120.0, trust_env=False) as client:
        r = client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False,
                  "options": {"temperature": temperature, "num_predict": max_tokens}},
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.+?)```", text, flags=re.S | re.I)
    sql = (m.group(1) if m else text).strip()
    return sql.rstrip(";").strip()


def ask(question: str) -> dict:
    if not warehouse.available():
        return {"ok": False, "error": "Warehouse not built yet. Run `make all` first."}

    allowed = set(warehouse.loaded_tables())
    messages = [
        {"role": "system", "content": SQL_SYSTEM.format(schema=warehouse.schema_prompt())},
        {"role": "user", "content": question},
    ]
    attempts = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = _chat(messages)
        except httpx.HTTPError as e:
            return {"ok": False, "error": f"LLM unavailable ({e.__class__.__name__}). Is Ollama running?"}
        sql = extract_sql(raw)
        try:
            safe_sql = validate(sql, allowed)
            rows = warehouse.query(safe_sql)
        except (UnsafeSQL, Exception) as e:           # validation or execution error → self-correct
            err = f"{e.__class__.__name__}: {e}"
            attempts.append({"sql": sql, "error": err})
            logger.info(f"[SQL agent] attempt {attempt} failed: {err}")
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"That query failed: {err}\nFix it and return only the corrected SQL."},
            ]
            continue

        preview = rows[:30]
        try:
            answer = _chat([
                {"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": f"Question: {question}\nSQL: {safe_sql}\nResult ({len(rows)} rows): {preview}"},
            ], temperature=0.2, max_tokens=200)
        except httpx.HTTPError:
            answer = f"Query returned {len(rows)} rows."
        return {"ok": True, "question": question, "sql": safe_sql, "rows": rows,
                "answer": answer, "attempts": attempts + [{"sql": safe_sql, "error": None}]}

    return {"ok": False, "question": question, "error": "Could not produce a valid query.", "attempts": attempts}


# ─────────────────────────────────────────────────────────────────────────────

FEATURE_LABELS = {
    "max_msgs_per_min": "peak prompts per minute",
    "max_msgs_per_min_7d": "peak prompts per minute (7d)",
    "gap_cv": "regularity of gaps between prompts (low = machine-like)",
    "gap_cv_7d": "regularity of gaps between prompts over 7d (low = machine-like)",
    "max_tz_7d": "distinct time zones in 7 days",
    "n_tz": "distinct time zones today",
    "concurrent_device_minutes": "minutes with two devices in session at once",
    "concurrent_device_minutes_7d": "minutes with two devices in session at once (7d)",
    "night_share": "share of prompts at 00:00-05:59",
    "night_share_7d": "share of prompts at night (7d)",
    "reask_share_7d": "share of re-asked prompts (7d)",
    "gap_mean_sec": "average seconds between prompts",
    "code_share": "share of prompts containing code",
    "msg_len_mean": "average prompt length",
    "msg_len_cv_7d": "variation in prompt length (low = templated)",
    "hour_entropy": "spread of activity across hours of the day",
    "session_minutes_7d": "minutes in AI sessions (7d)",
    "delegation_share_7d": "share of 'do it for me' prompts (7d)",
    "msgs": "prompts today",
    "msgs_7d": "prompts in 7 days",
}


def explain_user(user_id: str, dt: str | None = None) -> dict:
    score_rows = warehouse.query(
        """SELECT * FROM ads_user_risk_score_1d
           WHERE user_id = ? AND dt = COALESCE(?, (SELECT MAX(dt) FROM ads_user_risk_score_1d WHERE user_id = ?))""",
        [user_id, dt, user_id],
    )
    if not score_rows:
        return {"ok": False, "error": f"No risk score for {user_id}"}
    s = score_rows[0]
    reasons = [s["reason_1"], s["reason_2"], s["reason_3"]]
    feat = warehouse.query("SELECT * FROM ads_user_features_1d WHERE user_id = ? AND dt = ?", [user_id, s["dt"]])
    med = warehouse.query(
        "SELECT " + ", ".join(f"median({r}) AS {r}" for r in reasons) + " FROM ads_user_features_1d WHERE dt = ?",
        [s["dt"]],
    )
    f, m = (feat[0] if feat else {}), (med[0] if med else {})
    evidence = [
        {"feature": r, "label": FEATURE_LABELS.get(r, r.replace("_", " ")),
         "value": _r(f.get(r)), "population_median": _r(m.get(r))}
        for r in reasons
    ]
    fallback = (
        f"{user_id} ranks in the top {s['risk_rank_pct']:.1%} of risk scores on {s['dt']} (score {s['risk_score']:.3f}). "
        + "Main drivers: " + "; ".join(f"{e['label']} = {e['value']} vs median {e['population_median']}" for e in evidence)
        + (f". Rules fired: {s['rule_reasons']}." if s.get("rule_reasons") else ".")
    )
    try:
        note = _chat([
            {"role": "system", "content": "You are a risk analyst writing a 3-sentence case note. State what pattern "
                                          "the evidence suggests (e.g. automation, account sharing, bulk extraction), "
                                          "cite the numbers vs the median, and recommend review/monitor/no action. No markdown."},
            {"role": "user", "content": f"Score: {s['risk_score']:.3f}, rank top {s['risk_rank_pct']:.1%}. "
                                        f"Rules fired: {s.get('rule_reasons') or 'none'}. Evidence: {evidence}"},
        ], temperature=0.2, max_tokens=220)
    except httpx.HTTPError:
        note = fallback
    return {"ok": True, "user_id": user_id, "dt": s["dt"], "risk_score": s["risk_score"],
            "risk_rank_pct": s["risk_rank_pct"], "rule_reasons": s.get("rule_reasons"),
            "evidence": evidence, "case_note": note, "template_note": fallback}


def _r(v):
    return round(float(v), 3) if isinstance(v, (int, float)) and v is not None else v
