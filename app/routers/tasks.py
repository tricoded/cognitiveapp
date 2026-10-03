# app/routers/tasks.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models import Task          # adjust if your model name differs

router = APIRouter(prefix="/tasks", tags=["Tasks"])


class TaskUpdate(BaseModel):
    status:         Optional[str]  = None
    completed_at:   Optional[str]  = None   # accepts None to clear it
    actual_minutes: Optional[int]  = None


@router.get("/")
def get_tasks(status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Task)
    if status:
        q = q.filter(Task.status == status)
    return q.order_by(Task.created_at.desc()).all()


@router.patch("/{task_id}")
def update_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")

    if data.status is not None:
        task.status = data.status
    if "completed_at" in data.model_fields_set:
        task.completed_at = (
            datetime.fromisoformat(data.completed_at)
            if data.completed_at else None
        )
    if "actual_minutes" in data.model_fields_set:
        task.actual_minutes = data.actual_minutes

    db.commit()
    db.refresh(task)
    return task
