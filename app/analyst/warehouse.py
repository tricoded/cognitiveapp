"""
Read-only DuckDB view of the Spark warehouse for the API and the LLM analyst.

Spark builds the Parquet tables offline; the API never needs a JVM. On first
use (and whenever the Parquet files change) we load the serving tables into
an in-memory DuckDB, then disable external access and lock the config, so
even a query that slipped past sql_guard cannot read other files.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb

ROOT = Path(os.getenv("PIPELINE_ROOT", "pipeline_data"))
WAREHOUSE = ROOT / "warehouse"

# table → one-line description (fed to the LLM as schema context)
SERVING_TABLES = {
    "dws_user_ai_1d":         "one row per user per day: daily AI-usage aggregates",
    "ads_user_features_1d":   "one row per user per day: model features incl. trailing-7-day windows",
    "ads_user_cdi_1d":        "one row per user per day: Cognitive Dependency Index (0-100) and its components",
    "ads_user_risk_score_1d": "one row per user per day (test window): LightGBM risk score, rule hits, top-3 SHAP reasons",
}

_lock = threading.Lock()
_con: duckdb.DuckDBPyConnection | None = None
_signature: tuple | None = None


def _files_signature() -> tuple:
    sig = []
    for t in SERVING_TABLES:
        d = WAREHOUSE / t
        if d.exists():
            files = sorted(d.rglob("*.parquet"))
            sig.append((t, len(files), max((f.stat().st_mtime for f in files), default=0)))
    return tuple(sig)


def available() -> bool:
    return any((WAREHOUSE / t).exists() for t in SERVING_TABLES)


def connection() -> duckdb.DuckDBPyConnection:
    global _con, _signature
    with _lock:
        sig = _files_signature()
        if _con is not None and sig == _signature:
            return _con
        con = duckdb.connect(":memory:")
        for t in SERVING_TABLES:
            d = WAREHOUSE / t
            if d.exists() and any(d.rglob("*.parquet")):
                glob = (d / "**" / "*.parquet").as_posix()
                con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{glob}', hive_partitioning = true)")
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        if _con is not None:
            _con.close()
        _con, _signature = con, sig
        return con


def loaded_tables() -> list[str]:
    con = connection()
    return [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()]


def schema_prompt() -> str:
    """Compact schema description for the text-to-SQL prompt."""
    con = connection()
    lines = []
    for t in loaded_tables():
        cols = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
            [t],
        ).fetchall()
        lines.append(f"TABLE {t} -- {SERVING_TABLES.get(t, '')}")
        lines.append("  " + ", ".join(f"{c} {ty}" for c, ty in cols))
    return "\n".join(lines)


def query(sql: str, params: list | None = None) -> list[dict]:
    con = connection()
    with _lock:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
