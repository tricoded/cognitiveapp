"""
Offline simulation of the nudge experiment.

Assumed true success rates per nudge variant (P(task completed within 2h
after the nudge)). The point is to show the bandit converges to the best arm
and how much regret it pays vs a fixed 25/25/25/25 A/B split.

    python -m pipeline.experiments.bandit_sim
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.decision.bandit import simulate  # noqa: E402

TRUE_RATES = {"reflect": 0.18, "task_reminder": 0.31, "break_timer": 0.22, "show_stats": 0.15}


def main(n_rounds: int = 3000, seeds: int = 20, img_dir: str = "docs/img", out: str = "pipeline_data/reports"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    best = max(TRUE_RATES.values())
    ab_regret = np.cumsum(np.full(n_rounds, best - np.mean(list(TRUE_RATES.values()))))
    runs = [simulate(TRUE_RATES, n_rounds, seed=s) for s in range(seeds)]
    regret = np.mean([r["cum_regret"] for r in runs], axis=0)
    share_best = np.mean([[p == "task_reminder" for p in r["picks"]] for r in runs], axis=0)
    rolling = np.convolve(share_best, np.ones(100) / 100, mode="valid")

    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ax[0].plot(regret, label="Thompson sampling")
    ax[0].plot(ab_regret, "--", label="fixed A/B split")
    ax[0].set(title="Cumulative regret (lost task completions)", xlabel="nudges shown")
    ax[0].legend()
    ax[1].plot(rolling)
    ax[1].axhline(0.25, ls="--", c="gray")
    ax[1].set(title="Share of traffic on best variant (rolling 100)", xlabel="nudges shown", ylim=(0, 1))
    fig.tight_layout()
    Path(img_dir).mkdir(parents=True, exist_ok=True)
    fig.savefig(Path(img_dir) / "bandit_convergence.png", dpi=130)

    summary = {
        "true_rates": TRUE_RATES, "rounds": n_rounds, "seeds": seeds,
        "final_regret_bandit": round(float(regret[-1]), 1),
        "final_regret_ab": round(float(ab_regret[-1]), 1),
        "regret_reduction": round(1 - float(regret[-1] / ab_regret[-1]), 3),
        "best_arm_share_last_500": round(float(share_best[-500:].mean()), 3),
    }
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "bandit_sim.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
