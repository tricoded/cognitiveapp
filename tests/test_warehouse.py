"""DuckDB serving layer: loads Parquet, and blocks file access even without sql_guard."""

import duckdb
import pandas as pd
import pytest

from app.analyst import warehouse


@pytest.fixture()
def tiny_warehouse(tmp_path, monkeypatch):
    d = tmp_path / "warehouse" / "ads_user_risk_score_1d" / "dt=2026-07-30"
    d.mkdir(parents=True)
    pd.DataFrame({"user_id": ["u1", "u2"], "risk_score": [0.9, 0.1]}).to_parquet(d / "part-0.parquet")
    (tmp_path / "secret.csv").write_text("password\nhunter2\n")
    monkeypatch.setattr(warehouse, "WAREHOUSE", tmp_path / "warehouse")
    monkeypatch.setattr(warehouse, "_con", None)
    monkeypatch.setattr(warehouse, "_signature", None)
    return tmp_path


def test_loads_partitioned_parquet(tiny_warehouse):
    assert warehouse.loaded_tables() == ["ads_user_risk_score_1d"]
    rows = warehouse.query("SELECT user_id, dt FROM ads_user_risk_score_1d ORDER BY risk_score DESC")
    assert rows[0]["user_id"] == "u1" and str(rows[0]["dt"]) == "2026-07-30"


def test_file_access_blocked_even_if_guard_bypassed(tiny_warehouse):
    secret = (tiny_warehouse / "secret.csv").as_posix()
    with pytest.raises(duckdb.Error):
        warehouse.query(f"SELECT * FROM read_csv_auto('{secret}')")
    with pytest.raises(duckdb.Error):
        warehouse.query("SET enable_external_access = true")
