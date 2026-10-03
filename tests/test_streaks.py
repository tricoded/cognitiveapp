# tests/test_streaks.py

from unittest.mock import MagicMock
from datetime import date, datetime, timedelta
from app.ml.streaks import get_streak


def make_completed(days_ago: int):
    t = MagicMock()
    t.status = "completed"
    d = date.today() - timedelta(days=days_ago)
    t.completed_at = datetime(d.year, d.month, d.day, 10, 0)
    return t


def test_no_tasks_returns_zeros():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    r = get_streak(db, user_id=0)
    assert r == {"current": 0, "longest": 0, "today_count": 0}

def test_only_today_streak_is_1():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [make_completed(0)]
    r = get_streak(db, user_id=0)
    assert r["current"] == 1
    assert r["today_count"] == 1

def test_3_consecutive_days_streak():
    db = MagicMock()
    tasks = [make_completed(i) for i in range(3)]  # today, yesterday, 2 days ago
    db.query.return_value.filter.return_value.all.return_value = tasks
    r = get_streak(db, user_id=0)
    assert r["current"] == 3

def test_gap_breaks_streak():
    db = MagicMock()
    # Today + 3 days ago (gap on day 1 and 2)
    tasks = [make_completed(0), make_completed(3)]
    db.query.return_value.filter.return_value.all.return_value = tasks
    r = get_streak(db, user_id=0)
    assert r["current"] == 1   # only today counts

def test_multiple_tasks_same_day():
    db = MagicMock()
    tasks = [make_completed(0), make_completed(0), make_completed(0)]
    db.query.return_value.filter.return_value.all.return_value = tasks
    r = get_streak(db, user_id=0)
    assert r["current"] == 1      # still 1 day
    assert r["today_count"] == 3  # but 3 tasks today

def test_longest_streak_tracked():
    db = MagicMock()
    # Days 5,6,7 ago = 3-day streak in the past (longer than current 1)
    tasks = [make_completed(0), make_completed(5), make_completed(6), make_completed(7)]
    db.query.return_value.filter.return_value.all.return_value = tasks
    r = get_streak(db, user_id=0)
    assert r["current"] == 1
    assert r["longest"] >= 3
