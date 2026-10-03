"""Risk-model metrics, in the vocabulary risk teams actually use."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve


def ks_stat(y: np.ndarray, score: np.ndarray) -> float:
    """Kolmogorov–Smirnov: max separation between the score CDFs of bad vs good."""
    fpr, tpr, _ = roc_curve(y, score)
    return float(np.max(tpr - fpr))


def at_top(y: np.ndarray, score: np.ndarray, frac: float) -> tuple[float, float]:
    """Precision and recall when we review only the top `frac` highest scores."""
    k = max(1, int(round(len(score) * frac)))
    idx = np.argsort(-score, kind="stable")[:k]
    tp = y[idx].sum()
    return float(tp / k), float(tp / max(1, y.sum()))


def summarize(y, score) -> dict:
    y, score = np.asarray(y).astype(int), np.asarray(score, dtype=float)
    p1, r1 = at_top(y, score, 0.01)
    p5, r5 = at_top(y, score, 0.05)
    return {
        "auc": round(float(roc_auc_score(y, score)), 4),
        "ks": round(ks_stat(y, score), 4),
        "pr_auc": round(float(average_precision_score(y, score)), 4),
        "precision@1%": round(p1, 4),
        "recall@1%": round(r1, 4),
        "precision@5%": round(p5, 4),
        "recall@5%": round(r5, 4),
    }


def recall_by_segment(y, score, segment, frac: float = 0.05) -> dict:
    """Recall at the top-`frac` threshold, split by ground-truth risk type."""
    y, score, segment = np.asarray(y), np.asarray(score, float), np.asarray(segment, dtype=object)
    k = max(1, int(round(len(score) * frac)))
    # exact top-k (stable), same as at_top(); a `score >= threshold` cut would
    # flag every tied row and overstate recall for coarse scores like rule points
    flagged = np.zeros(len(score), dtype=bool)
    flagged[np.argsort(-score, kind="stable")[:k]] = True
    out = {}
    for s in sorted({x for x in segment[y == 1] if x is not None}):
        m = (segment == s) & (y == 1)
        out[s] = round(float(flagged[m].mean()), 4) if m.any() else None
    return out


def markdown_table(results: dict[str, dict]) -> str:
    cols = ["auc", "ks", "pr_auc", "precision@1%", "recall@1%", "precision@5%", "recall@5%"]
    lines = ["| model | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for name, m in results.items():
        lines.append(f"| {name} | " + " | ".join(f"{m[c]:.3f}" for c in cols) + " |")
    return "\n".join(lines)
