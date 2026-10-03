from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON
from sqlalchemy.sql import func
from datetime import datetime
from app.database import Base


class Memory(Base):
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    category = Column(String(50))
    importance_score = Column(Float, default=0.5)
    access_count = Column(Integer, default=0)
    embedding_index = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    priority = Column(String(50), default="Medium")
    category = Column(String(50), default="Other")
    due_date = Column(DateTime, nullable=True)
    estimated_minutes = Column(Integer, default=60)
    notes = Column(Text, nullable=True)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    actual_minutes = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    energy_level_start = Column(Integer, nullable=True)  # 1-10 scale
    energy_level_end = Column(Integer, nullable=True)
    distraction_count = Column(Integer, default=0)
    time_of_day = Column(String(20), nullable=True)  # "morning", "afternoon", "evening"
 
class SkillEvidence(Base):
    __tablename__ = "skill_evidence"
    
    id = Column(Integer, primary_key=True, index=True)
    skill_name = Column(String(100), nullable=False)
    task_id = Column(Integer, nullable=False)  # Reference to tasks.id
    completed_at = Column(DateTime, server_default=func.now())
    quality_score = Column(Float, default=0.5)  # 0.0-1.0 scale
    time_taken = Column(Integer)  # minutes

class Profile(Base):
    """User profile with productivity patterns."""
    __tablename__ = "profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, default="default")
    
    # Energy patterns
    peak_hours = Column(JSON, default=lambda: [9, 10, 11])  # Best focus hours
    low_hours = Column(JSON, default=lambda: [14, 15])       # Low energy hours
    
    # Preferences
    focus_duration = Column(Integer, default=90)  # Minutes per focus block
    break_duration = Column(Integer, default=15)  # Minutes per break
    daily_goals = Column(Integer, default=3)      # Max tasks per day
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=True)
    tags = Column(Text, default="[]")  # stored as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AIUsageLog(Base):
    __tablename__ = "ai_usage_logs"

    id            = Column(Integer, primary_key=True, index=True)
    tool_name     = Column(String(100), nullable=False)   # "ChatGPT", "Copilot", etc.
    category      = Column(String(50),  nullable=False)   # "Writing", "Coding", etc.
    duration_mins = Column(Integer,     nullable=False)   # how long used
    quality       = Column(String(20),  default="active") # "active" | "passive"
    notes         = Column(Text,        nullable=True)
    used_at       = Column(DateTime,    default=datetime.utcnow)
    created_at    = Column(DateTime,    default=datetime.utcnow)


class AIUsageEvent(Base):
    """
    One prompt sent on an AI platform, as reported by the browser extension.
    Only on-device prompt *features* are stored: the prompt text never
    leaves the browser. Same schema as the simulator / warehouse ODS layer.
    """
    __tablename__ = "ai_usage_events"

    id          = Column(Integer, primary_key=True, index=True)
    event_id    = Column(String(40), unique=True, index=True, nullable=False)
    user_id     = Column(String(40), default="me", index=True)
    device_id   = Column(String(60), nullable=True)
    platform    = Column(String(40), nullable=False)
    event_type  = Column(String(30), default="message_sent")
    event_ts    = Column(DateTime, default=datetime.utcnow, index=True)   # server receive time
    client_ts   = Column(DateTime, nullable=True)
    tz_offset   = Column(Integer, default=0)
    session_id  = Column(String(60), nullable=True)
    msg_len     = Column(Integer, nullable=True)
    has_code    = Column(Integer, default=0)
    is_question = Column(Integer, default=0)
    is_reask    = Column(Integer, default=0)
    prompt_kind = Column(String(20), nullable=True)   # "delegation" | "learning"
    app_version = Column(String(20), nullable=True)


class DecisionLog(Base):
    """Every decision-engine call that led to an intervention, for audit + experiment analysis."""
    __tablename__ = "decision_logs"

    id         = Column(Integer, primary_key=True, index=True)
    decided_at = Column(DateTime, default=datetime.utcnow, index=True)
    platform   = Column(String(40))
    action     = Column(String(20), nullable=False)      # allow / soft_nudge / hard_nudge / cool_down
    variant    = Column(String(30), nullable=True)       # which nudge message (bandit arm)
    reasons    = Column(JSON, default=list)              # strategy reason codes
    features   = Column(JSON, default=dict)              # snapshot of inputs
    outcome    = Column(Integer, nullable=True)          # 1 = task completed within 2h, 0 = not, NULL = pending
    outcome_at = Column(DateTime, nullable=True)
