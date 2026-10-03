"""
Thompson-sampling bandit that picks WHICH nudge to show.

Deciding *that* we nudge is the rules' job (engine.py). Deciding *how* is an
experiment: each variant is an arm; the reward is 1 if the user completes a
task within 2 hours after the nudge, else 0. The bandit shifts traffic to the
variant that works, while still exploring the others.

State is rebuilt from the decision log each time (successes / failures per
arm), so there is no hidden mutable state to lose.
"""

from __future__ import annotations

import numpy as np

VARIANTS = {
    "reflect":       "You've been prompting for a while. What do you actually want to understand here?",
    "task_reminder": "Your top task is still open: {top_task}. Want to switch to it?",
    "break_timer":   "Take a 5-minute break. The problem will still be there, and you'll see it more clearly.",
    "show_stats":    "This week: {ai_mins} min of AI, CDI {cdi}. Is this the balance you want?",
}


class ThompsonBandit:
    def __init__(self, arms: list[str], prior: tuple[float, float] = (1.0, 1.0), seed: int | None = None):
        self.arms = list(arms)
        self.alpha = {a: prior[0] for a in self.arms}
        self.beta = {a: prior[1] for a in self.arms}
        self.rng = np.random.default_rng(seed)

    def update(self, arm: str, reward: int) -> None:
        if reward:
            self.alpha[arm] += 1
        else:
            self.beta[arm] += 1

    def choose(self) -> str:
        draws = {a: self.rng.beta(self.alpha[a], self.beta[a]) for a in self.arms}
        return max(draws, key=draws.get)

    def posterior(self) -> dict:
        out = {}
        for a in self.arms:
            al, be = self.alpha[a], self.beta[a]
            out[a] = {
                "mean": round(al / (al + be), 4),
                "trials": int(al + be - 2),
                "successes": int(al - 1),
                # P(this arm is best), by Monte Carlo
            }
        samples = np.column_stack([self.rng.beta(self.alpha[a], self.beta[a], 4000) for a in self.arms])
        best = np.bincount(samples.argmax(axis=1), minlength=len(self.arms)) / len(samples)
        for a, p in zip(self.arms, best):
            out[a]["p_best"] = round(float(p), 4)
        return out

    @classmethod
    def from_history(cls, history: list[tuple[str, int]], seed: int | None = None) -> "ThompsonBandit":
        b = cls(list(VARIANTS), seed=seed)
        for arm, reward in history:
            if arm in b.alpha and reward is not None:
                b.update(arm, int(reward))
        return b


def simulate(true_rates: dict[str, float], n_rounds: int = 2000, seed: int = 0) -> dict:
    """Offline simulation: does the bandit find the best nudge, and how fast?"""
    rng = np.random.default_rng(seed)
    b = ThompsonBandit(list(true_rates), seed=seed)
    best_rate = max(true_rates.values())
    picks, regret, cum = [], [], 0.0
    for _ in range(n_rounds):
        arm = b.choose()
        reward = int(rng.random() < true_rates[arm])
        b.update(arm, reward)
        cum += best_rate - true_rates[arm]
        picks.append(arm)
        regret.append(cum)
    return {"picks": picks, "cum_regret": regret, "posterior": b.posterior()}
