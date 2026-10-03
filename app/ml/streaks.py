# app/ml/streaks.py

from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models import Task


def get_streak(db: Session, user_id: int) -> dict:
    """
    Calculates the current completion streak (consecutive days with
    at least one completed task) and today's completion count.
    """
    completed = db.query(Task).filter(Task.status == "completed").all()

    if not completed:
        return {"current": 0, "longest": 0, "today_count": 0}

    # Dates that had at least one completion
    dates_with_completions = set(
        t.completed_at.date()
        for t in completed
        if t.completed_at
    )

    today      = date.today()
    streak     = 0
    check_date = today

    # Walk backwards from today
    while check_date in dates_with_completions:
        streak    += 1
        check_date -= timedelta(days=1)

    # Longest streak
    longest    = streak
    all_dates  = sorted(dates_with_completions)
    run        = 1
    for i in range(1, len(all_dates)):
        if (all_dates[i] - all_dates[i - 1]).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    today_count = sum(
        1 for t in completed
        if t.completed_at and t.completed_at.date() == today
    )

    return {
        "current":     streak,
        "longest":     longest,
        "today_count": today_count,
    }
