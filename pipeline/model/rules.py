"""Expert-rule baseline: YAML rules → score + reason codes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

RULES_PATH = Path(__file__).parent / "rules.yaml"


def load_rules(path: Path = RULES_PATH) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["rules"]


def apply_rules(df: pd.DataFrame, rules: list[dict] | None = None) -> tuple[np.ndarray, list[list[str]]]:
    """Return (score per row, list of fired reason codes per row)."""
    rules = rules or load_rules()
    filled = df.fillna(0)
    score = np.zeros(len(df))
    fired = np.zeros((len(df), len(rules)), dtype=bool)
    for j, r in enumerate(rules):
        hit = filled.eval(r["when"]).to_numpy(bool)
        fired[:, j] = hit
        score += hit * r["weight"]
    codes = [r["code"] for r in rules]
    reasons = [[codes[j] for j in np.flatnonzero(row)] for row in fired]
    return score, reasons
