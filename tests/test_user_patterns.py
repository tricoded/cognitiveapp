# tests/test_user_patterns.py

from unittest.mock import MagicMock, patch
from datetime import datetime, date, timedelta
from app.ml.user_patterns import analyze_user_patterns


def make_completed_task(completed_hour=10, completed_weekday=0,
                        actual_mins=60, est_mins=60, category="Work"):
    t = MagicMock()
    t.status            = "completed"
    t.actual_minutes    = actual_mins
    t.estimated_minutes = est_mins
    t.category          = category

    # Build a datetime with specific hour and weekday
    today   = date.today()
    # Find a past date with the right weekday
    days_back = (today.weekday() - completed_weekday) % 7 or 7
    d = today - timedelta(days=days_back)
    t.completed_at = datetime(d.year, d.month, d.day, completed_hour, 0)
    return t


def test_empty_returns_empty_dict():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    result = analyze_user_patterns(db, user_id=0)
    assert result == {}

def test_under_3_returns_empty():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        make_completed_task()
    ]
    result = analyze_user_patterns(db, user_id=0)
    assert result == {}

def test_peak_hour_detected():
    db = MagicMock()
    # 5 tasks at 9am, 1 task at 3pm
    tasks = (
        [make_completed_task(completed_hour=9) for _ in range(5)] +
        [make_completed_task(completed_hour=15)]
    )
    db.query.return_value.filter.return_value.all.return_value = tasks
    result = analyze_user_patterns(db, user_id=0)
    assert result["peak_hour"] == 9
    assert result["peak_hour_label"] == "morning"

def test_underestimate_detected():
    db = MagicMock()
    # Always takes 30 mins longer than estimated
    tasks = [
        make_completed_task(actual_mins=90, est_mins=60)
        for _ in range(5)
    ]
    db.query.return_value.filter.return_value.all.return_value = tasks
    result = analyze_user_patterns(db, user_id=0)
    assert result["tends_to"] == "underestimate"
    assert result["avg_estimate_error_min"] == 30.0

def test_overestimate_detected():
    db = MagicMock()
    tasks = [
        make_completed_task(actual_mins=30, est_mins=60)
        for _ in range(5)
    ]
    db.query.return_value.filter.return_value.all.return_value = tasks
    result = analyze_user_patterns(db, user_id=0)
    assert result["tends_to"] == "overestimate"

def test_fastest_category():
    db = MagicMock()
    tasks = (
        [make_completed_task(actual_mins=20, category="Personal") for _ in range(3)] +
        [make_completed_task(actual_mins=120, category="Development") for _ in range(3)]
    )
    db.query.return_value.filter.return_value.all.return_value = tasks
    result = analyze_user_patterns(db, user_id=0)
    assert result["fastest_category"] == "Personal"
    assert result["slowest_category"] == "Development"
