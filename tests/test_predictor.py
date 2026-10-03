# tests/test_predictor.py

from unittest.mock import MagicMock, patch
from datetime import datetime, date, timedelta
from app.ml.task_predictor import TaskDifficultyPredictor


def make_task(title="Fix bug", priority="High", category="Development",
              est_mins=60, actual_mins=None, due_days=None):
    t = MagicMock()
    t.title             = title
    t.priority          = priority
    t.category          = category
    t.estimated_minutes = est_mins
    t.actual_minutes    = actual_mins
    t.status            = "completed" if actual_mins else "pending"
    t.created_at        = datetime.now()
    if due_days is not None:
        t.due_date = MagicMock()
        t.due_date.date.return_value = date.today() + timedelta(days=due_days)
    else:
        t.due_date = None
    return t


# ── Fallback behavior (untrained) ───────────────────────────────────────────

def test_untrained_returns_estimated():
    p    = TaskDifficultyPredictor.__new__(TaskDifficultyPredictor)
    p.model, p.is_trained = None, False
    task = make_task(est_mins=45)
    assert p.predict(task) == 45

def test_untrained_returns_60_if_no_estimate():
    p    = TaskDifficultyPredictor.__new__(TaskDifficultyPredictor)
    p.model, p.is_trained = None, False
    task = make_task(est_mins=None)
    assert p.predict(task) == 60


# ── Training ─────────────────────────────────────────────────────────────────

def test_train_requires_5_tasks():
    p     = TaskDifficultyPredictor.__new__(TaskDifficultyPredictor)
    p.model, p.is_trained = None, False
    tasks = [make_task(actual_mins=30 + i * 10) for i in range(4)]  # only 4
    result = p.train(tasks)
    assert result == False
    assert p.is_trained == False

def test_train_succeeds_with_5_tasks():
    p     = TaskDifficultyPredictor.__new__(TaskDifficultyPredictor)
    p.model, p.is_trained = None, False
    tasks = [make_task(actual_mins=30 + i * 15) for i in range(5)]
    with patch.object(p, "_save"):    # don't write to disk
        result = p.train(tasks)
    assert result == True
    assert p.is_trained == True

def test_train_ignores_tasks_without_actual_minutes():
    p     = TaskDifficultyPredictor.__new__(TaskDifficultyPredictor)
    p.model, p.is_trained = None, False
    tasks = (
        [make_task(actual_mins=60) for _ in range(3)] +   # valid
        [make_task(actual_mins=None) for _ in range(10)]  # invalid — no actual time
    )
    result = p.train(tasks)
    assert result == False  # only 3 valid, need 5


# ── Prediction output ─────────────────────────────────────────────────────────

def test_predict_rounds_to_nearest_5():
    p = TaskDifficultyPredictor.__new__(TaskDifficultyPredictor)
    p.is_trained = True
    p.model = MagicMock()
    p.model.predict.return_value = [47.3]  # raw output
    task = make_task()
    result = p.predict(task)
    assert result % 5 == 0  # must be multiple of 5
    assert result == 45     # rounds 47.3 → 45

def test_predict_minimum_5_minutes():
    p = TaskDifficultyPredictor.__new__(TaskDifficultyPredictor)
    p.is_trained = True
    p.model = MagicMock()
    p.model.predict.return_value = [1.0]  # very low prediction
    result = p.predict(make_task())
    assert result >= 5


# ── Auto-retrain thresholds ──────────────────────────────────────────────────

def test_retrain_triggers_at_5():
    p = TaskDifficultyPredictor.__new__(TaskDifficultyPredictor)
    p.model, p.is_trained = None, False

    db    = MagicMock()
    tasks = [make_task(actual_mins=60) for _ in range(5)]

    # ✅ Single .filter() call — matches actual code
    db.query.return_value.filter.return_value.all.return_value = tasks

    with patch.object(p, "train", return_value=True) as mock_train:
        p.retrain_if_ready(db)
        mock_train.assert_called_once()

def test_retrain_does_not_trigger_at_6():
    p = TaskDifficultyPredictor.__new__(TaskDifficultyPredictor)
    p.model, p.is_trained = None, False

    db    = MagicMock()
    tasks = [make_task(actual_mins=60) for _ in range(6)]
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = tasks

    with patch.object(p, "train", return_value=True) as mock_train:
        p.retrain_if_ready(db)
        mock_train.assert_not_called()
