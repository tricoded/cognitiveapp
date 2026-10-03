"""
Train and compare risk models on the ADS feature table.

    python -m pipeline.model.train

Unit of prediction: one (user_id, dt) snapshot. Label = the user is a known
risky account AND dt is on/after the risk onset date.

Split: out-of-time. Train on earlier dates, test on later dates, and
validate for early stopping on the tail of the train period, so nothing
from the future leaks into training. Random K-fold on time-series risk data
inflates metrics and is the #1 mistake to avoid here.

Models compared:
  1. rules      — expert YAML rules (day-1 baseline, no labels needed)
  2. iforest    — IsolationForest (unsupervised, no labels needed)
  3. lightgbm   — gradient-boosted trees with labels
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from sklearn.ensemble import IsolationForest

from pipeline.model.evaluate import markdown_table, recall_by_segment, summarize
from pipeline.model.rules import apply_rules

ID_COLS = ["user_id", "dt"]


def load_features(root: Path) -> pd.DataFrame:
    table = ds.dataset(root / "warehouse" / "ads_user_features_1d", format="parquet", partitioning="hive").to_table()
    df = table.to_pandas()
    df["dt"] = df["dt"].astype(str)
    # Spark DECIMAL columns arrive as Python Decimal objects; models need floats
    for c in df.columns:
        if c not in ("user_id", "dt") and df[c].dtype == object:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df


def attach_labels(df: pd.DataFrame, root: Path) -> pd.DataFrame:
    labels = pd.read_csv(root / "raw" / "labels" / "risk_labels.csv")
    df = df.merge(labels[["user_id", "risk_type", "onset_dt"]], on="user_id", how="left")
    df["label"] = (df["risk_type"].notna() & (df["dt"] >= df["onset_dt"].fillna("9999"))).astype(int)
    # Segment of the positive: which risk type; negatives are "normal"
    df["segment"] = np.where(df["label"] == 1, df["risk_type"], "normal")
    return df


def time_split(df: pd.DataFrame, warmup_days: int = 6, test_frac: float = 0.3, val_frac: float = 0.15):
    dts = sorted(df["dt"].unique())[warmup_days:]      # drop days with incomplete 7d windows
    n_test = int(len(dts) * test_frac)
    n_val = int(len(dts) * val_frac)
    test_dts = dts[-n_test:]
    val_dts = dts[-(n_test + n_val):-n_test]
    train_dts = dts[:-(n_test + n_val)]
    pick = lambda s: df[df["dt"].isin(s)].reset_index(drop=True)
    return pick(train_dts), pick(val_dts), pick(test_dts), (train_dts, val_dts, test_dts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="pipeline_data")
    ap.add_argument("--docs-img", default="docs/img")
    a = ap.parse_args()
    root = Path(a.root)
    reports, models_dir = root / "reports", root / "models"
    reports.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    df = attach_labels(load_features(root), root)
    features = [c for c in df.columns if c not in ID_COLS + ["risk_type", "onset_dt", "label", "segment"]]
    train, val, test, (tr_d, va_d, te_d) = time_split(df)
    print(f"rows: train={len(train):,} val={len(val):,} test={len(test):,}  "
          f"pos rate train={train.label.mean():.2%} test={test.label.mean():.2%}")
    print(f"dates: train {tr_d[0]}..{tr_d[-1]}  val {va_d[0]}..{va_d[-1]}  test {te_d[0]}..{te_d[-1]}")

    results, seg_recall = {}, {}

    # 1. Rules
    rule_score, rule_reasons = apply_rules(test)
    results["rules (expert)"] = summarize(test.label, rule_score)
    seg_recall["rules (expert)"] = recall_by_segment(test.label, rule_score, test.segment)

    # 2. Isolation Forest (fit on train features only; labels unused)
    Xtr = train[features].fillna(0).to_numpy()
    iso = IsolationForest(n_estimators=300, contamination="auto", random_state=42, n_jobs=-1).fit(Xtr)
    iso_score = -iso.score_samples(test[features].fillna(0).to_numpy())
    results["isolation forest"] = summarize(test.label, iso_score)
    seg_recall["isolation forest"] = recall_by_segment(test.label, iso_score, test.segment)

    # 3. LightGBM
    pos_w = (train.label == 0).sum() / max(1, (train.label == 1).sum())
    clf = lgb.LGBMClassifier(
        n_estimators=2000, learning_rate=0.03, num_leaves=31, min_child_samples=50,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
        scale_pos_weight=pos_w, random_state=42, verbose=-1,
    )
    clf.fit(
        train[features], train.label,
        eval_set=[(val[features], val.label)], eval_metric="auc",
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    lgb_score = clf.predict_proba(test[features])[:, 1]
    results["lightgbm"] = summarize(test.label, lgb_score)
    seg_recall["lightgbm"] = recall_by_segment(test.label, lgb_score, test.segment)

    table = markdown_table(results)
    print("\nOut-of-time test results\n" + table)
    print("\nRecall @ top-5% by risk type:")
    for m, r in seg_recall.items():
        print(f"  {m:<18} {r}")

    # Feature importance / explanations
    shap_top = explain(clf, test, features, Path(a.docs_img))

    # Persist model + metadata
    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "train_dates": [tr_d[0], tr_d[-1]], "val_dates": [va_d[0], va_d[-1]], "test_dates": [te_d[0], te_d[-1]],
        "n_train": len(train), "n_test": len(test), "best_iteration": int(clf.best_iteration_ or clf.n_estimators),
        "features": features, "metrics": results, "recall_by_type@5%": seg_recall, "shap_top_features": shap_top,
    }
    joblib.dump({"model": clf, "features": features}, models_dir / "risk_lgbm.joblib")
    (models_dir / "risk_lgbm.meta.json").write_text(json.dumps(meta, indent=2))
    (reports / "model_metrics.json").write_text(json.dumps(meta, indent=2))
    (reports / "model_comparison.md").write_text(table + "\n")

    # Score the test window back into the warehouse (ADS)
    write_scores(root, test, lgb_score, rule_score, rule_reasons, clf, features)
    print(f"\nSaved model -> {models_dir}/risk_lgbm.joblib, scores -> warehouse/ads_user_risk_score_1d")


def explain(clf, test: pd.DataFrame, features: list[str], img_dir: Path) -> list[dict]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import shap

    sample = test[features].sample(min(5000, len(test)), random_state=0)
    sv = shap.TreeExplainer(clf).shap_values(sample)
    sv = sv[1] if isinstance(sv, list) else sv
    mean_abs = np.abs(sv).mean(axis=0)
    order = np.argsort(-mean_abs)

    img_dir.mkdir(parents=True, exist_ok=True)
    shap.summary_plot(sv, sample, max_display=15, show=False)
    plt.tight_layout()
    plt.savefig(img_dir / "shap_summary.png", dpi=130)
    plt.close()
    return [{"feature": features[i], "mean_abs_shap": round(float(mean_abs[i]), 4)} for i in order[:15]]


def write_scores(root, test, lgb_score, rule_score, rule_reasons, clf, features):
    """Top-3 SHAP reasons per row, so every flag is explainable downstream."""
    contrib = clf.booster_.predict(test[features], pred_contrib=True)[:, :-1]
    top = np.argsort(-contrib, axis=1)[:, :3]
    out = pd.DataFrame({
        "user_id": test.user_id,
        "risk_score": np.round(lgb_score, 5),
        "rule_score": rule_score,
        "rule_reasons": [",".join(r) for r in rule_reasons],
        "reason_1": [features[i] for i in top[:, 0]],
        "reason_2": [features[i] for i in top[:, 1]],
        "reason_3": [features[i] for i in top[:, 2]],
        "dt": test.dt,
    })
    out["risk_rank_pct"] = out.groupby("dt")["risk_score"].rank(pct=True, ascending=False).round(5)
    dest = root / "warehouse" / "ads_user_risk_score_1d"
    ds.write_dataset(
        __import__("pyarrow").Table.from_pandas(out, preserve_index=False), dest, format="parquet",
        partitioning=["dt"], partitioning_flavor="hive", existing_data_behavior="delete_matching",
    )


if __name__ == "__main__":
    main()
