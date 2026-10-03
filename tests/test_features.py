"""
Feature correctness on tiny hand-made data, through the real Spark SQL.
Skipped automatically when no JVM / PySpark is available (e.g. native Windows).
"""

import os
import shutil

import pytest

pyspark = pytest.importorskip("pyspark")
if not (os.getenv("JAVA_HOME") or shutil.which("java")):
    pytest.skip("no Java runtime", allow_module_level=True)
if os.name == "nt" and not os.getenv("HADOOP_HOME"):
    pytest.skip("Spark on Windows needs Hadoop winutils; run via WSL (scripts/wsl_run.sh)", allow_module_level=True)

from datetime import datetime, timedelta, timezone  # noqa: E402

from pipeline.spark.jobs import SQL_DIR, get_spark  # noqa: E402


@pytest.fixture(scope="module")
def spark():
    s = get_spark("test-features")
    yield s
    s.stop()


def _events(user, device, start, gaps_sec, tz=8, platform="chatgpt", kind="learning", reask=False):
    t, rows = start, []
    for i, g in enumerate([0] + gaps_sec):
        t = t + timedelta(seconds=g)
        rows.append(dict(
            event_id=f"{user}-{device}-{i}-{start.isoformat()}", user_id=user, device_id=device, platform=platform,
            event_type="message_sent", event_ts=t, client_ts=t, tz_offset=tz, session_id="x", msg_len=100,
            has_code=False, is_question=True, is_reask=reask, prompt_kind=kind, category="study",
            app_version="1.0.0", dt=t.astimezone(timezone.utc).date().isoformat(),
        ))
    return rows


def _run(spark, rows):
    spark.createDataFrame(rows).createOrReplaceTempView("ods_ai_events")
    spark.sql((SQL_DIR / "dwd_ai_events_di.sql").read_text()).createOrReplaceTempView("dwd_ai_events_di")
    dws = spark.sql((SQL_DIR / "dws_user_ai_1d.sql").read_text())
    return {r.user_id: r for r in dws.collect()}, spark.table("dwd_ai_events_di")


def test_bot_vs_human_regularity_and_burst(spark):
    day = datetime(2026, 6, 1, 2, 0, tzinfo=timezone.utc)
    rows = _events("bot", "d1", day, [3] * 60) + _events("human", "d2", day, [40, 95, 20, 300, 61, 150, 33, 400])
    dws, _ = _run(spark, rows)
    assert dws["bot"].gap_cv == pytest.approx(0.0, abs=1e-9)          # perfectly regular
    assert dws["human"].gap_cv > 0.5
    assert dws["bot"].max_msgs_per_min >= 20                          # 60 prompts in ~3 minutes
    assert dws["human"].max_msgs_per_min <= 2


def test_dedup_and_sessionization(spark):
    day = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    rows = _events("u", "d1", day, [60, 60]) + _events("u", "d1", day + timedelta(hours=2), [60])
    rows.append(dict(rows[0]))                                        # retry duplicate
    dws, dwd = _run(spark, rows)
    assert dwd.count() == 5                                           # duplicate removed
    assert dws["u"].sessions == 2                                     # 2h gap > 30 min → new session
    assert dws["u"].msgs == 5


def test_concurrent_devices_and_timezones(spark):
    day = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    rows = (_events("shared", "phone", day, [60] * 30, tz=8)
            + _events("shared", "laptop", day + timedelta(minutes=5), [60] * 30, tz=-5))
    dws, _ = _run(spark, rows)
    r = dws["shared"]
    assert r.n_devices == 2 and r.n_tz == 2
    assert r.concurrent_device_minutes == pytest.approx(25.0, abs=0.5)   # sessions overlap 12:05–12:30


def test_night_share_uses_local_time(spark):
    # 18:00 UTC is 02:00 at UTC+8 → night
    rows = _events("n", "d", datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc), [60, 60], tz=8)
    dws, _ = _run(spark, rows)
    assert dws["n"].night_share == 1.0
