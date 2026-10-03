import pytest

from app.analyst.sql_guard import MAX_ROWS, UnsafeSQL, validate

ALLOWED = {"ads_user_features_1d", "ads_user_risk_score_1d"}


def test_simple_select_gets_limit():
    out = validate("SELECT user_id, msgs FROM ads_user_features_1d", ALLOWED)
    assert f"LIMIT {MAX_ROWS}" in out


def test_cte_and_join_allowed():
    sql = """WITH t AS (SELECT user_id, MAX(dt) AS dt FROM ads_user_risk_score_1d GROUP BY 1)
             SELECT f.user_id FROM ads_user_features_1d f JOIN t ON f.user_id = t.user_id LIMIT 10"""
    assert "LIMIT 10" in validate(sql, ALLOWED)


def test_large_limit_is_capped():
    assert f"LIMIT {MAX_ROWS}" in validate("SELECT * FROM ads_user_features_1d LIMIT 100000", ALLOWED)


@pytest.mark.parametrize("sql", [
    "DROP TABLE ads_user_features_1d",
    "DELETE FROM ads_user_features_1d",
    "INSERT INTO ads_user_features_1d VALUES (1)",
    "SELECT 1; DROP TABLE ads_user_features_1d",
    "SELECT * FROM users_secret",
    "SELECT * FROM read_parquet('/etc/passwd')",
    "SELECT * FROM read_csv_auto('C:/Users/secret.csv')",
    "SELECT getenv('HOME')",
    "COPY ads_user_features_1d TO 'out.csv'",
    "SELECT * FROM main.ads_user_features_1d",
    "PRAGMA database_list",
])
def test_rejects_unsafe(sql):
    with pytest.raises(UnsafeSQL):
        validate(sql, ALLOWED)
