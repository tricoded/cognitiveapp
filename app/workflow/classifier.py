from app.models import Task
from app.schemas import TaskCreate
from sqlalchemy.orm import Session

def classify_quadrant(urgency: float, importance: float) -> str:
    """
    Eisenhower Matrix classification.
    Both values are 0.0 to 1.0.
    Threshold at 0.5.
    """
    high_urgency = urgency >= 0.5
    high_importance = importance >= 0.5

    if high_urgency and high_importance:
        return "do_now"
    elif not high_urgency and high_importance:
        return "schedule"
    elif high_urgency and not high_importance:
        return "delegate"
    else:
        return "eliminate"

def create_task(db: Session, data: TaskCreate) -> Task:
    quadrant = classify_quadrant(data.urgency, data.importance)

    task = Task(
        title=data.description,
        description=data.description,
        urgency=data.urgency,
        importance=data.importance,
        quadrant=quadrant,
        due_date=data.due_date,
        status="pending"
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

def get_prioritized_tasks(db: Session) -> dict:
    """
    Returns tasks grouped by quadrant, sorted by urgency within each group.
    """
    all_tasks = db.query(Task).filter(Task.status != "done").all()

    grouped = {
        "do_now": [],
        "schedule": [],
        "delegate": [],
        "eliminate": []
    }

    for task in all_tasks:
        quadrant = task.quadrant or classify_quadrant(task.urgency, task.importance)
        grouped[quadrant].append(task)

    # Sort each group by urgency descending
    for key in grouped:
        grouped[key].sort(key=lambda t: t.urgency, reverse=True)

    return grouped

# ── Update task status ──────────────────────────────────────────────────
def update_task_status(db: Session, task_id: int, new_status: str) -> Task | None:
    """
    Updates the status of a task by ID.
    Valid statuses: pending, in_progress, done
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return None
    task.status = new_status
    db.commit()
    db.refresh(task)
    return task

# ── Delete a task ───────────────────────────────────────────────────────
def delete_task(db: Session, task_id: int) -> bool:
    """
    Deletes a task by ID.
    Returns True if deleted, False if not found.
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return False
    db.delete(task)
    db.commit()
    return True
