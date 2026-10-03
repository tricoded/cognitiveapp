"""
Real-time decision engine for AI-usage sessions.

Same shape as a risk-control decision engine: features in → ordered strategy
rules → one action + reason codes out, every decision logged for audit and
for measuring whether the intervention worked.

    fraud engine:      pass   / review     / step_up    / block
    this engine:       allow  / soft_nudge / hard_nudge / cool_down

The extension calls POST /decision on every 30s tick of an active session.
Features are computed on-device from prompts; prompt text never leaves the
browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ACTIONS = ["allow", "soft_nudge", "hard_nudge", "cool_down"]
SEVERITY = {a: i for i, a in enumerate(ACTIONS)}


@dataclass
class SessionFeatures:
    platform: str
    session_minutes: float
    msgs_in_session: int
    msgs_last_5min: int = 0
    delegation_share: float = 0.0     # share of "do it for me" prompts in session
    reask_share: float = 0.0          # share of prompts re-asking the previous one
    local_hour: int = 12
    today_total_mins: float = 0.0
    daily_budget_mins: float = 120.0
    open_high_priority_tasks: int = 0
    cdi: float | None = None          # latest Cognitive Dependency Index, if known


@dataclass
class Strategy:
    code: str
    action: str
    desc: str
    when: callable = field(repr=False)


# Ordered, reviewable strategy list. Highest-severity match wins; every match
# is returned as a reason code.
STRATEGIES: list[Strategy] = [
    Strategy("S01_OVER_BUDGET_HARD", "cool_down",
             "Daily AI budget exceeded by 50%+",
             lambda f: f.today_total_mins >= 1.5 * f.daily_budget_mins),
    Strategy("S02_DOOM_PROMPTING", "hard_nudge",
             "Re-asking loop: many re-asks in a long session",
             lambda f: f.reask_share >= 0.35 and f.msgs_in_session >= 8),
    Strategy("S03_LATE_NIGHT_BINGE", "hard_nudge",
             "Long session after midnight",
             lambda f: 0 <= f.local_hour <= 4 and f.session_minutes >= 30),
    Strategy("S04_OVER_BUDGET", "soft_nudge",
             "Daily AI budget reached",
             lambda f: f.today_total_mins >= f.daily_budget_mins),
    Strategy("S05_DELEGATION_HEAVY", "soft_nudge",
             "Mostly delegating, little learning, in a long session",
             lambda f: f.delegation_share >= 0.8 and f.msgs_in_session >= 10 and f.session_minutes >= 20),
    Strategy("S06_PRIORITY_NEGLECT", "soft_nudge",
             "Long AI session while high-priority tasks are open",
             lambda f: f.open_high_priority_tasks > 0 and f.session_minutes >= 45),
    Strategy("S07_HIGH_CDI", "soft_nudge",
             "Cognitive Dependency Index is high this week",
             lambda f: f.cdi is not None and f.cdi >= 60 and f.session_minutes >= 15),
]


def decide(f: SessionFeatures) -> dict:
    fired = [s for s in STRATEGIES if s.when(f)]
    if not fired:
        return {"action": "allow", "reasons": [], "reason_desc": []}
    action = max((s.action for s in fired), key=SEVERITY.__getitem__)
    return {
        "action": action,
        "reasons": [s.code for s in fired],
        "reason_desc": [s.desc for s in fired],
    }
