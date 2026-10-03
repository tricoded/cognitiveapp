from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# Memory schemas
class MemoryCreate(BaseModel):
    content: str
    category: str = "general"

class MemoryResponse(BaseModel):
    id: int
    content: str
    category: str
    importance_score: float
    access_count: int
    created_at: datetime

    class Config:
        from_attributes = True

# Task schemas (NEW PRODUCTIVITY-FOCUSED STRUCTURE)
class TaskCreate(BaseModel):
    title: str
    priority: str = "Medium"
    category: str = "Other"
    due_date: Optional[datetime] = None
    estimated_minutes: int = 60
    notes: Optional[str] = None

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    due_date: Optional[datetime] = None
    estimated_minutes: Optional[int] = None
    notes: Optional[str] = None
    status: Optional[str] = None

class TaskResponse(BaseModel):
    id: int
    title: str
    priority: str
    category: str
    due_date: Optional[datetime] = None
    estimated_minutes: int
    notes: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    actual_minutes: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    energy_level_start: Optional[int] = None
    energy_level_end: Optional[int] = None
    distraction_count: int = 0
    time_of_day: Optional[str] = None

    class Config:
        from_attributes = True

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = "default"
    top_k: int = 5

class PlanRequest(BaseModel):
    context: Optional[str] = None

# ── ML Schemas ──────────────────────────────────────────────
class PredictRequest(BaseModel):
    estimated_minutes: int = 60
    priority: str          = "Medium"
    category: str          = "Other"
    energy_level_start: int = 5
    distraction_count: int  = 0

class MLTrainResponse(BaseModel):
    status: str
    samples_used: Optional[int] = None
    mae_minutes: Optional[float] = None
    trained_at: Optional[str] = None
    ml_enabled: bool
    reason: Optional[str] = None
