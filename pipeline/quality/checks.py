"""
Data-quality monitoring for the AI-usage warehouse.

Runs after ODS/DWD/ADS are built and emits one alert per (dt, check) that
breaches its threshold. The goal is not just "something is wrong" but
*where*: every alert carries the dimension (platform, column, feature) that
localises the problem.

Checks
------
schema_contract   raw partition fields vs the expected contract (missing / unexpected)
volume            rows per platform vs trailing-7-day median (drops, spikes)
duplicate_rate    share of repeated event_id in ODS
null_rate         share of NULL in required columns in ODS
clock_skew        median (server event_ts − client_ts) per platform
feature_psi       Population Stability Index of key ADS features vs a reference window
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

EXPECTED_FIELDS = {
    "event_id", "user_id", "device_id", "platform", "event_type", "event_ts", "client_ts",
    "tz_offset", "session_id", "msg_len", "has_code", "is_question", "is_reask",
    "prompt_kind", "category", "app_version",
}
REQUIRED = ["event_id", "user_id", "device_id", "platform", "event_ts", "msg_len"]
PSI_FEATURES = ["msgs", "max_msgs_per_min", "gap_cv", "night_share", "msg_len_mean", "session_minutes"]

THRESHOLDS = {
    "duplicate_rate": 0.01,       # >1% duplicated event_id
    "null_rate": 0.005,           # >0.5% NULL in a required column
    "volume_drop": 0.50,          # platform volume < 50% of 7d median
    "volume_spike": 2.0,          # platform volume > 2× 7d median
    "clock_skew_sec": 300,        # median |lag| > 5 min
    "psi_warn": 0.10,
    "psi_alert": 0.25,
}


@dataclass
class Alert:
    dt: str
    check: str
    severity: str        # "warn" | "alert"
    dimension: str       # where: platform / column / feature
    value: float
    threshold: float
    detail: str


# ─────────────────────────────────────────────────────────────────────────────

def check_schema(raw_root: Path, dts: list[str], sample_lines: int = 500) -> list[Alert]:
    alerts = []
    for dt in dts:
        f = raw_root / f"dt={dt}" / "part-0000.jsonl"
        if not f.exists():
            alerts.append(Alert(dt, "schema_contract", "alert", "partition", 0, 1, "raw partition missing"))
            continue
        seen: set[str] = set()
        with f.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= sample_lines:
                    break
                seen |= set(json.loads(line).keys())
        missing, extra = EXPECTED_FIELDS - seen, seen - EXPECTED_FIELDS
        if missing or extra:
            alerts.append(Alert(
                dt, "schema_contract", "alert", ",".join(sorted(missing | extra)),
                len(missing) + len(extra), 0,
                f"missing={sorted(missing)} unexpected={sorted(extra)}",
            ))
    return alerts


def check_ods(wh, start: str, end: str) -> tuple[list[Alert], pd.DataFrame]:
    # Imported here so the pure-Python checks (schema, PSI) work without PySpark
    from pyspark.sql import functions as F

    ods = wh.read("ods_ai_events", start, end)

    per_dt = ods.groupBy("dt").agg(
        F.count("*").alias("rows"),
        F.countDistinct("event_id").alias("distinct_ids"),
        *[F.avg(F.col(c).isNull().cast("double")).alias(f"null_{c}") for c in REQUIRED],
    ).toPandas().sort_values("dt")

    per_platform = ods.groupBy("dt", "platform").agg(
        F.count("*").alias("rows"),
        F.expr("percentile_approx(unix_timestamp(event_ts) - unix_timestamp(client_ts), 0.5)").alias("median_lag_sec"),
    ).toPandas().sort_values(["platform", "dt"])

    alerts: list[Alert] = []
    for r in per_dt.itertuples():
        dup = 1 - r.distinct_ids / r.rows if r.rows else 0
        if dup > THRESHOLDS["duplicate_rate"]:
            alerts.append(Alert(r.dt, "duplicate_rate", "alert", "event_id", round(dup, 4),
                                THRESHOLDS["duplicate_rate"], f"{r.rows - r.distinct_ids:,} repeated event_ids"))
        for c in REQUIRED:
            v = getattr(r, f"null_{c}")
            if v > THRESHOLDS["null_rate"]:
                alerts.append(Alert(r.dt, "null_rate", "alert", c, round(v, 4), THRESHOLDS["null_rate"],
                                    f"{v:.2%} of rows have NULL {c}"))

    for platform, g in per_platform.groupby("platform"):
        g = g.reset_index(drop=True)
        baseline = g["rows"].rolling(7, min_periods=3).median().shift(1)
        for i, r in g.iterrows():
            b = baseline.iloc[i]
            if pd.notna(b) and b > 0:
                ratio = r["rows"] / b
                if ratio < THRESHOLDS["volume_drop"]:
                    alerts.append(Alert(r["dt"], "volume", "alert", platform, round(ratio, 3), THRESHOLDS["volume_drop"],
                                        f"{r['rows']:,} rows vs 7d median {b:,.0f}"))
                elif ratio > THRESHOLDS["volume_spike"]:
                    alerts.append(Alert(r["dt"], "volume", "warn", platform, round(ratio, 3), THRESHOLDS["volume_spike"],
                                        f"{r['rows']:,} rows vs 7d median {b:,.0f}"))
            lag = r["median_lag_sec"]
            if pd.notna(lag) and abs(lag) > THRESHOLDS["clock_skew_sec"]:
                alerts.append(Alert(r["dt"], "clock_skew", "alert", platform, float(lag), THRESHOLDS["clock_skew_sec"],
                                    f"median server-client lag {lag:+.0f}s"))
    return alerts, per_dt


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index with quantile bins from the reference sample."""
    expected, actual = expected[~np.isnan(expected)], actual[~np.isnan(actual)]
    if len(expected) < 50 or len(actual) < 50:
        return float("nan")
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    e = np.histogram(expected, edges)[0] / len(expected)
    a = np.histogram(actual, edges)[0] / len(actual)
    e, a = np.clip(e, 1e-4, None), np.clip(a, 1e-4, None)
    return float(np.sum((a - e) * np.log(a / e)))


def check_feature_drift(wh, start: str, end: str, ref_days: int = 14) -> tuple[list[Alert], pd.DataFrame]:
    ads = wh.read("ads_user_features_1d", start, end).select("dt", *PSI_FEATURES).toPandas()
    dts = sorted(ads["dt"].unique())
    ref = ads[ads["dt"].isin(dts[:ref_days])]
    rows, alerts = [], []
    for dt in dts[ref_days:]:
        cur = ads[ads["dt"] == dt]
        for feat in PSI_FEATURES:
            v = psi(ref[feat].to_numpy(float), cur[feat].to_numpy(float))
            rows.append({"dt": dt, "feature": feat, "psi": v})
            if v >= THRESHOLDS["psi_warn"]:
                sev = "alert" if v >= THRESHOLDS["psi_alert"] else "warn"
                alerts.append(Alert(dt, "feature_psi", sev, feat, round(v, 3),
                                    THRESHOLDS["psi_alert" if sev == "alert" else "psi_warn"],
                                    f"PSI vs first {ref_days} days"))
    return alerts, pd.DataFrame(rows)


def run_all(wh, start: str, end: str, dts: list[str], out_dir: Path) -> list[Alert]:
    alerts = check_schema(wh.raw, dts)
    a, per_dt = check_ods(wh, start, end)
    alerts += a
    a, psi_df = check_feature_drift(wh, start, end)
    alerts += a
    alerts.sort(key=lambda x: (x.dt, x.check))

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dq_alerts.json").write_text(json.dumps([asdict(x) for x in alerts], indent=2))
    per_dt.to_csv(out_dir / "dq_daily_metrics.csv", index=False)
    psi_df.to_csv(out_dir / "dq_feature_psi.csv", index=False)
    return alerts
