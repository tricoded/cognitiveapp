from app.decision.bandit import ThompsonBandit, simulate
from app.decision.engine import SessionFeatures, decide


def f(**kw):
    base = dict(platform="chatgpt", session_minutes=5, msgs_in_session=3)
    base.update(kw)
    return SessionFeatures(**base)


def test_normal_session_allowed():
    assert decide(f())["action"] == "allow"


def test_highest_severity_wins_and_all_reasons_kept():
    out = decide(f(today_total_mins=200, daily_budget_mins=120, reask_share=0.5, msgs_in_session=20))
    assert out["action"] == "cool_down"
    assert {"S01_OVER_BUDGET_HARD", "S02_DOOM_PROMPTING", "S04_OVER_BUDGET"} <= set(out["reasons"])


def test_late_night_binge():
    assert decide(f(local_hour=2, session_minutes=40))["action"] == "hard_nudge"


def test_bandit_prefers_better_arm():
    res = simulate({"a": 0.1, "b": 0.4}, n_rounds=1500, seed=1)
    assert res["picks"][-500:].count("b") > 400
    assert res["posterior"]["b"]["p_best"] > 0.95


def test_bandit_from_history_ignores_unknown_arms():
    b = ThompsonBandit.from_history([("reflect", 1), ("nope", 1), ("reflect", 0)])
    assert b.alpha["reflect"] == 2 and b.beta["reflect"] == 2
