from fastapi import FastAPI, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
from fastapi.responses import JSONResponse
import joblib
import httpx
import asyncio
import os
from sqlalchemy.orm import Session
from app.database import engine, get_db, Base
from typing import Union, List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.models import Profile, Memory, SkillEvidence, Task, Note, AIUsageLog
from app.schemas import (
    MemoryCreate, MemoryResponse,
    QueryRequest,
)
from app.memory.store import (
    create_memory,
    retrieve_relevant_memories,
    get_all_memories,
    delete_memory_by_id
)
from app.llm.agent import (
    generate_daily_plan, 
    query_with_memory, 
    auto_archive_completed, 
    daily_priority_refresh,
    smart_chat,
)
from app.analytics.productivity import (
    get_estimation_analytics,
    get_productivity_by_hour,
    get_skill_inventory,
    calculate_estimation_accuracy,
    get_time_of_day_category
)
from app.ml.task_predictor import predictor
from app.decision.store import record_task_completion
from app.websocket.manager import manager
from app.cache.redis_cache import cache
from app.middleware.rate_limit import limiter, _rate_limit_exceeded_handler, RateLimitExceeded
from app.schemas import PredictRequest, MLTrainResponse
from app.routers import ai_usage, tasks, decision, risk, news
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== OLLAMA CONFIG ====================
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "ollama")
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")

if OLLAMA_HOST.startswith("http"):
    OLLAMA_BASE_URL = OLLAMA_HOST
else:
    OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

logger.info(f"[CONFIG] OLLAMA_BASE_URL = {OLLAMA_BASE_URL}")

# ==================== LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # ── STARTUP ──
    logger.info("Starting up...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized")

    # ── AUTO ARCHIVE + PRIORITY REFRESH ──────────────────────
    try:
        db = next(get_db())
        try:
            archived   = auto_archive_completed(db)   # only completed tasks 24h+ old
            escalated  = daily_priority_refresh(db)   # bump priorities by deadline
            if archived:
                logger.info(f"[STARTUP] Archived {archived} old completed tasks")
            if escalated:
                logger.info(f"[STARTUP] Escalated {len(escalated)} task priorities")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[STARTUP] Maintenance tasks failed (non-fatal): {e}")

    # ── OLLAMA WARMUP ──
    logger.info("[WARMUP] Pre-warming Ollama mistral model...")
    try:
        async with httpx.AsyncClient(timeout=300.0, trust_env=False) as client:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={"model": "mistral", "prompt": "hi", "stream": False}
            )
            if resp.is_success:
                logger.info(f"[WARMUP] ✅ Ollama ready! Status: {resp.status_code}")
            else:
                logger.warning(
                    f"[WARMUP] ⚠️ Ollama not ready (non-fatal): HTTP {resp.status_code} "
                    f"from {OLLAMA_BASE_URL} - is `ollama serve` running with the mistral model pulled?"
                )
    except Exception as e:
        logger.warning(f"[WARMUP] ⚠️ Warmup failed (non-fatal): {e}")

    yield  # ← App runs here

    # ── SHUTDOWN ──
    logger.info("Shutting down...")

# ==================== APP ====================
app = FastAPI(
    title="Cognitive Memory and Workflow Assistant",
    description="AI-powered second brain with task management",
    version="1.0.0",
    lifespan=lifespan
)

# ==================== MIDDLEWARE ====================
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== ROUTERS (if you have them) ====================
app.include_router(ai_usage.router)
app.include_router(tasks.router)
app.include_router(decision.router)
app.include_router(risk.router)
app.include_router(news.router)

# app.include_router(chat.router)
# app.include_router(profile.router)
# app.include_router(notes.router)

# ==================== WEBSOCKET ENDPOINT ====================
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint for real-time updates.
    Usage: ws://localhost:8000/ws/user123
    """
    await manager.connect(websocket, user_id)
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            # Echo back with timestamp
            response = {
                "user_id": user_id,
                "message": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            await manager.send_personal_message(response, user_id)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)

# ==================== HEALTH ====================
@app.get("/health")
async def health_check():
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e.__class__.__name__}"

    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
        ollama_status = "up" if r.status_code == 200 else f"http {r.status_code}"
    except Exception:
        ollama_status = "down"

    return {
        "status":    "healthy" if db_status == "connected" else "degraded",
        "database":  db_status,
        "ollama":    ollama_status,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ─── SESSION COMPATIBILITY ROUTES ─────────────────────────

@app.get("/memory/{session_id}")
def get_session_memory(session_id: str, db: Session = Depends(get_db)):
    memories = get_all_memories(db)
    return [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": mem.content
        }
        for i, mem in enumerate(memories)
    ]

@app.delete("/memory/{session_id}")
def clear_session_memory(session_id: str, db: Session = Depends(get_db)):
    db.query(Memory).delete()
    db.commit()
    return {"status": "cleared", "session_id": session_id}

# ─── MEMORY ROUTES ────────────────────────────────────────

@app.post("/memory", response_model=MemoryResponse)
def add_memory(data: MemoryCreate, db: Session = Depends(get_db)):
    return create_memory(db, data)

@app.get("/memory", response_model=list[MemoryResponse])
def list_memories(db: Session = Depends(get_db)):
    return get_all_memories(db)

@app.post("/memory/search", response_model=list[MemoryResponse])
def search_memories(request: QueryRequest, db: Session = Depends(get_db)):
    return retrieve_relevant_memories(db, request.query, top_k=request.top_k)

@app.delete("/memory/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db)):
    return delete_memory_by_id(db, memory_id)

# ─── LLM AGENT ROUTES ─────────────────────────────────────

@app.get("/plan")
def get_daily_plan(db: Session = Depends(get_db)):
    """Generate intelligent daily plan based on tasks, energy, and priorities."""
    from datetime import datetime, date
    
    try:
        # Get today's date
        today = date.today()
        
        # Get pending/in-progress tasks
        tasks = db.query(Task).filter(
            Task.status.in_(["pending", "in_progress"])
        ).order_by(
            Task.priority.desc(),
            Task.due_date
        ).limit(10).all()
        
        if not tasks:
            return {
                "date": str(today),
                "message": "No pending tasks! 🎉",
                "morning_tasks": [],
                "afternoon_tasks": [],
                "evening_tasks": []
            }
        
        # Get profile (if exists)
        profile = db.query(Profile).first()
        
        # Simple scheduling: High priority in morning, others in afternoon
        morning_tasks = []
        afternoon_tasks = []
        evening_tasks = []
        
        for task in tasks:
            task_info = {
                "id": task.id,
                "title": task.title,
                "priority": task.priority,
                "estimated_minutes": task.estimated_minutes or 30,
                "category": task.category,
                "due_date": str(task.due_date) if task.due_date else None
            }
            
            # Schedule based on priority
            if task.priority in ["Critical", "High"]:
                morning_tasks.append({
                    **task_info,
                    "suggested_time": "09:00",
                    "reason": "High priority - peak focus hours"
                })
            elif task.priority == "Medium":
                afternoon_tasks.append({
                    **task_info,
                    "suggested_time": "14:00",
                    "reason": "Medium priority - afternoon slot"
                })
            else:
                evening_tasks.append({
                    **task_info,
                    "suggested_time": "16:00",
                    "reason": "Low priority - end of day"
                })
        
        return {
            "date": str(today),
            "total_tasks": len(tasks),
            "morning_tasks": morning_tasks[:3],  # Max 3 per block
            "afternoon_tasks": afternoon_tasks[:3],
            "evening_tasks": evening_tasks[:2],
            "focus_blocks": [
                {
                    "start": "09:00",
                    "end": "10:30",
                    "type": "Deep Work",
                    "task_count": len(morning_tasks[:2])
                },
                {
                    "start": "10:45",
                    "end": "12:00",
                    "type": "Deep Work",
                    "task_count": len(morning_tasks[2:3])
                }
            ],
            "tips": [
                "Start with your highest priority task",
                "Take breaks between focus blocks",
                "Review progress at end of day"
            ]
        }
        
    except Exception as e:
        import traceback
        print(f"ERROR in /plan: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query")
def query_assistant(request: QueryRequest, db: Session = Depends(get_db)):
    response = query_with_memory(db, request.query)
    return {"response": response}

# ==================== SCHEDULING HELPER FUNCTIONS ====================

def optimize_schedule(tasks: List[Dict]) -> List[Dict]:
    """
    Optimize task schedule using priority-based algorithm.
    Returns tasks sorted by optimal execution order.
    """
    # Priority weights
    priority_weights = {
        "urgent": 10,
        "high": 7,
        "medium": 5,
        "low": 3
    }
    
    # Score each task
    scored_tasks = []
    for task in tasks:
        # Base score from priority
        score = priority_weights.get(task.get('priority', 'medium'), 5)
        
        # Boost score if due_date is soon
        if task.get('due_date'):
            try:
                deadline = datetime.fromisoformat(task['due_date'].replace('Z', '+00:00'))
                days_until = (deadline - datetime.utcnow()).days
                if days_until <= 1:
                    score += 5  # Due tomorrow or today
                elif days_until <= 3:
                    score += 3  # Due within 3 days
            except:
                pass
        
        # Reduce score for long tasks (spread them out)
        duration = task.get('predicted_duration', task.get('estimated_minutes', 60))
        if duration > 120:  # Tasks over 2 hours
            score -= 2
        
        scored_tasks.append({
            **task,
            'optimization_score': score
        })
    
    # Sort by score (highest first)
    sorted_tasks = sorted(scored_tasks, key=lambda x: x['optimization_score'], reverse=True)
    
    # Create time slots
    current_time = datetime.utcnow()
    schedule = []
    
    for task in sorted_tasks:
        duration = task.get('predicted_duration', task.get('estimated_minutes', 60))
        
        schedule.append({
            'task_id': task.get('id'),
            'title': task.get('title'),
            'priority': task.get('priority'),
            'start_time': current_time.isoformat(),
            'end_time': (current_time + timedelta(minutes=duration)).isoformat(),
            'duration_minutes': duration,
            'optimization_score': task['optimization_score']
        })
        
        # Add 15-minute break between tasks
        current_time += timedelta(minutes=duration + 15)
    
    return schedule


def calculate_schedule_score(schedule: List[Dict]) -> float:
    """
    Calculate quality score for a schedule (0-100).
    Higher is better.
    """
    if not schedule:
        return 0.0
    
    score = 100.0
    
    # Penalty for long work sessions without breaks
    total_duration = sum(task['duration_minutes'] for task in schedule)
    if total_duration > 480:  # More than 8 hours
        score -= 20
    
    # Bonus for high-priority tasks scheduled early
    high_priority_early = sum(
        1 for i, task in enumerate(schedule[:3]) 
        if task.get('priority') in ['urgent', 'high']
    )
    score += high_priority_early * 5
    
    # Penalty for too many tasks in one day
    if len(schedule) > 8:
        score -= (len(schedule) - 8) * 3
    
    # Bonus for balanced task distribution
    avg_duration = total_duration / len(schedule) if schedule else 0
    if 30 <= avg_duration <= 90:  # Sweet spot: 30-90 min tasks
        score += 10
    
    return max(0.0, min(100.0, score))  # Clamp between 0-100

# ─── CHAT ROUTE ───────────────────────────────────────────

class ChatRequest(BaseModel):
    message: Union[str, None] = None
    query: Union[str, None] = None
    session_id: str = "default"
    model_config = {"extra": "allow"}

@limiter.limit("20/minute")
@app.post("/chat")
def chat_endpoint(request: ChatRequest, req: Request, db: Session = Depends(get_db)):
    try:
        user_input = request.query or request.message
        if not user_input:
            raise HTTPException(
                status_code=400,
                detail="Either 'message' or 'query' field must be provided"
            )
        response = query_with_memory(db, user_input)
        return {"response": response}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
 
 # ─── SMART AI CHAT ROUTE ──────────────────────────────────
from app.llm.agent import smart_chat

class SmartChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    conversation_history: Optional[List[Dict]] = []
    session_state: dict = {}
    user_id: int = 0

@limiter.limit("30/minute")
@app.post("/ai/chat")
def smart_chat_endpoint(
    request: SmartChatRequest,
    req: Request,
    db: Session = Depends(get_db)
):
    """
    Task-aware AI chat. Understands natural language for:
    - Creating/listing/completing tasks
    - Analytics and productivity insights  
    - General conversation
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    result = smart_chat(
        message=request.message,
        user_id=request.user_id,
        db=db,
        session_state=request.session_state,
        conversation_history=request.conversation_history or []
    )
    return result

# ─── PROFILE ROUTE ────────────────────────────────────────

class UserProfile(BaseModel):
    name: str
    timezone: str
    work_start: str
    work_end: str
    peak_hours: List[int]
    low_hours: List[int]
    focus_duration: int
    break_duration: int
    priorities: List[str]

@app.post("/profile")
def save_profile(profile: UserProfile, db: Session = Depends(get_db)):
    try:
        from app.memory.store import store_memory
        profile_text = f"""
User Profile:
- Name: {profile.name}
- Timezone: {profile.timezone}
- Work Hours: {profile.work_start} - {profile.work_end}
- Peak Energy: {', '.join([f'{h:02d}:00' for h in profile.peak_hours])}
- Low Energy: {', '.join([f'{h:02d}:00' for h in profile.low_hours])}
- Focus Duration: {profile.focus_duration} minutes
- Break Duration: {profile.break_duration} minutes
- Priorities: {', '.join(profile.priorities)}
"""
        store_memory(
            db=db,
            content=profile_text,
            category="profile",
            metadata={"type": "user_preferences"}
        )
        return {"status": "success", "message": "Profile saved"}
    except Exception as e:
        print(f"Profile save error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── TASK SCHEMAS ─────────────────────────────────────────

class TaskCreateRequest(BaseModel):
    title: str
    priority: str = "Medium"
    category: str = "Other"
    due_date: Optional[str] = None
    estimated_minutes: int = 60
    notes: str = ""
    status: str = "pending"

class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    due_date: Optional[str] = None
    estimated_minutes: Optional[int] = None
    notes: Optional[str] = None
    status: Optional[str] = None

# ─── TASK ROUTES ──────────────────────────────────────────

@app.post("/tasks")
def create_new_task(task: TaskCreateRequest, db: Session = Depends(get_db)):
    try:
        db_task = Task(
            title=task.title,
            priority=task.priority,
            category=task.category,
            due_date=datetime.fromisoformat(task.due_date) if task.due_date else None,
            estimated_minutes=task.estimated_minutes,
            notes=task.notes,
            status=task.status
        )
        db.add(db_task)
        db.commit()
        db.refresh(db_task)
        return {"status": "success", "id": db_task.id}
    except Exception as e:
        print(f"Task creation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks")
def get_all_tasks(db: Session = Depends(get_db)):
    try:
        tasks = db.query(Task).order_by(Task.due_date).all()
        return [
            {
                "id": t.id,
                "title": t.title,
                "priority": t.priority,
                "category": t.category,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "estimated_minutes": t.estimated_minutes,
                "notes": t.notes,
                "status": t.status
            }
            for t in tasks
        ]
    except Exception as e:
        print(f"Task retrieval error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}")
def get_task_by_id(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "id": task.id,
        "title": task.title,
        "priority": task.priority,
        "category": task.category,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "estimated_minutes": task.estimated_minutes,
        "notes": task.notes,
        "status": task.status
    }

@app.put("/tasks/{task_id}")
def update_task(
    task_id: int,
    task_update: TaskUpdateRequest,
    db: Session = Depends(get_db)
):
    """Update any field on a task"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        if task_update.title is not None:
            task.title = task_update.title
        if task_update.priority is not None:
            task.priority = task_update.priority
        if task_update.category is not None:
            task.category = task_update.category
        if task_update.due_date is not None:
            task.due_date = datetime.fromisoformat(task_update.due_date)
        if task_update.estimated_minutes is not None:
            task.estimated_minutes = task_update.estimated_minutes
        if task_update.notes is not None:
            task.notes = task_update.notes
        if task_update.status is not None:
            task.status = task_update.status

        db.commit()
        db.refresh(task)
        return {
            "status": "success",
            "id": task.id,
            "updated_fields": task_update.model_dump(exclude_none=True)
        }
    except Exception as e:
        print(f"Task update error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/tasks/{task_id}")
def remove_task_by_id(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"status": "success"}

# ─── TIME TRACKING ROUTES ─────────────────────────────────

# FIX #1: Changed @app.patch to @app.post
@app.post("/tasks/{task_id}/start")
def start_task_tracking(
    task_id: int,
    energy_level: int = 5,
    db: Session = Depends(get_db)
):
    """Start tracking a task with energy level"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.started_at = datetime.now()
    task.energy_level_start = energy_level
    task.time_of_day = get_time_of_day_category()
    task.status = "in_progress"
    db.commit()

    return {
        "status": "started",
        "started_at": task.started_at.isoformat(),
        "time_of_day": task.time_of_day
    }

@app.post("/tasks/{task_id}/complete")
def complete_task_with_tracking(
    task_id: int,
    energy_level: int = 5,
    distractions: int = 0,
    db: Session = Depends(get_db)
):
    """Complete task and calculate actual time + accuracy"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.completed_at = datetime.now()
    task.energy_level_end = energy_level
    task.distraction_count = distractions

    if task.started_at:
        delta = task.completed_at - task.started_at
        task.actual_minutes = int(delta.total_seconds() / 60)
    else:
        task.actual_minutes = task.estimated_minutes

    task.status = "completed"
    db.commit()

    accuracy = calculate_estimation_accuracy(task)

    if 90 <= accuracy <= 110:
        feedback = "Accurate estimate"
    elif accuracy < 50:
        feedback = f"Underestimated by {100 - accuracy:.0f}%"
    elif accuracy > 150:
        feedback = f"Overestimated by {accuracy - 100:.0f}%"
    else:
        feedback = f"Off by {abs(100 - accuracy):.0f}%"

    # Auto-retrain at 5/10/20/every-10 completions (passes ORM rows, which is
    # what the predictor featurizes)
    predictor.retrain_if_ready(db)

    # Close the loop on any recent nudge: completing a task within 2h counts
    # as a success for the nudge variant that was shown.
    record_task_completion(db, task.completed_at)

    return {
        "status": "completed",
        "estimated_min": task.estimated_minutes,
        "actual_min": task.actual_minutes,
        "accuracy_pct": round(accuracy, 1),
        "feedback": feedback
    }

# ─── NOTE SCHEMAS ─────────────────────────────────────────

class NoteCreateRequest(BaseModel):
    title: str  # ← ADD THIS
    content: str
    tags: Optional[List[str]] = []

class NoteUpdateRequest(BaseModel):
    title: Optional[str] = None  # ← ADD THIS
    content: Optional[str] = None
    tags: Optional[List[str]] = None

# ─── ANALYTICS ROUTES ─────────────────────────────────────

@app.get("/analytics/estimation")
def estimation_accuracy_report(db: Session = Depends(get_db)):
    """How good are your time estimates? (estimated vs actual)"""
    return get_estimation_analytics(db)

# ─── MISSING ANALYTICS ROUTES ─────────────────────────────

@app.get("/analytics/productivity-hours")
def productivity_hours_report(db: Session = Depends(get_db)):
    """When are you ACTUALLY productive?"""
    return get_productivity_by_hour(db)


@app.get("/analytics/overview")
def analytics_overview(db: Session = Depends(get_db)):
    """Full analytics dashboard"""
    estimation = get_estimation_analytics(db)
    productivity = get_productivity_by_hour(db)
    
    # Task summary
    total_tasks = db.query(Task).count()
    completed = db.query(Task).filter(Task.status == "completed").count()
    in_progress = db.query(Task).filter(Task.status == "in_progress").count()
    
    return {
        "summary": {
            "total_tasks": total_tasks,
            "completed": completed,
            "in_progress": in_progress,
            "pending": total_tasks - completed - in_progress,
            "completion_rate_pct": round(completed / total_tasks * 100, 1) if total_tasks > 0 else 0
        },
        "estimation": estimation,
        "productivity": productivity
    }

@app.get("/analytics/cached")
@limiter.limit("20/minute")
async def get_cached_analytics(request: Request, db: Session = Depends(get_db)):
    """Get cached analytics to reduce database load."""
    
    # Try to get from cache first
    cached = cache.get("analytics:overview")
    if cached:
        return {"cached": True, **cached}
    
    # Calculate fresh data
    total_tasks = db.query(Task).count()
    completed = db.query(Task).filter(Task.status == "completed").count()
    
    result = {
        "total_tasks": total_tasks,
        "completed_tasks": completed,
        "completion_rate": (completed / total_tasks * 100) if total_tasks > 0 else 0
    }
    
    # Store in cache for 5 minutes
    cache.set("analytics:overview", result, ttl=300)
    
    return {"cached": False, **result}

# ─── SKILLS ROUTES ────────────────────────────────────────

@app.post("/skills/record")
def record_skill_evidence(
    task_id: int,
    skill_name: str,
    quality: float,
    db: Session = Depends(get_db)
):
    """Record skill evidence from task completion"""
    if not (0.0 <= quality <= 1.0):
        raise HTTPException(400, "quality must be between 0.0 and 1.0")
    
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, f"Task {task_id} not found")
    
    # Create skill evidence record
    evidence = SkillEvidence(
        task_id=task_id,
        skill_name=skill_name,
        quality_score=quality,
        time_taken=task.actual_minutes
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    
    return {
        "status": "recorded",
        "task_id": task_id,
        "skill": skill_name,
        "quality": quality,
        "evidence_id": evidence.id
    }


@app.get("/skills/inventory")
def skills_inventory_report(db: Session = Depends(get_db)):
    """What can you ACTUALLY do?"""
    return get_skill_inventory(db)

@app.get("/plan/ml")
@limiter.limit("10/minute")
async def get_ml_powered_plan(request: Request, db: Session = Depends(get_db)):
    """
    AI-powered task scheduling using ML predictions.
    Falls back to rule-based scheduling if ML model is unavailable.
    """
    try:
        # Use the global predictor singleton
        ml_enabled = predictor.is_trained

        # Fetch pending tasks
        tasks = db.query(Task).filter(Task.status == "pending").all()
        
        if not tasks:
            return {
                "schedule": [],
                "ml_enabled": ml_enabled,
                "message": "No pending tasks to schedule"
            }
        
        # Transform to dict format
        task_list = []
        for task in tasks:
            task_dict = {
                'id': task.id,
                'title': task.title,
                'priority': task.priority,
                'category': task.category,
                'estimated_minutes': task.estimated_minutes,
                'due_date': task.due_date.isoformat() if task.due_date else None,
            }
            
            # Use ML prediction if available, otherwise fall back to estimate
            if ml_enabled:
                prediction = predictor.predict_duration(task_dict)
                task_dict['predicted_duration'] = prediction['predicted_actual_minutes']
                task_dict['ml_insight'] = prediction.get('insight', '')
            else:
                task_dict['predicted_duration'] = task.estimated_minutes
                task_dict['ml_insight'] = 'Train model first for ML predictions'

            task_list.append(task_dict)
        
        # Generate optimized schedule
        schedule = optimize_schedule(task_list)
        
        # Calculate quality score
        quality_score = calculate_schedule_score(schedule)
        
        return {
            "schedule": schedule,
            "ml_enabled": ml_enabled,
            "optimization_score": round(quality_score, 2),
            "total_tasks": len(schedule),
            "estimated_total_time": sum(t['duration_minutes'] for t in schedule),
            "recommendations": generate_schedule_recommendations(schedule)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scheduling error: {str(e)}")

@app.post("/ml/train", response_model=MLTrainResponse)
async def train_ml_model(db: Session = Depends(get_db)):
    """Manually trigger retraining on all completed tasks."""
    tasks = db.query(Task).filter(
        Task.status == "completed",
        Task.actual_minutes > 0
    ).all()
    return predictor.train_report(tasks)
 
 
@app.post("/ml/predict")
async def predict_task(req: PredictRequest):
    """Predict how long a task will actually take."""
    result = predictor.predict_duration(req.dict())
    return result
 
 
@app.get("/ml/status")
async def ml_model_status():
    """Return ML model status and last training metadata."""
    return predictor.get_status()
 
 
@app.get("/ml/feature-importance")
async def ml_feature_importance():
    """Return which factors affect your task duration most."""
    importance = predictor.get_feature_importance()
    if importance is None:
        return {"error": "No model trained yet. POST /ml/train first."}
    return {
        "feature_importance": importance,
        "insight": "Higher value = stronger influence on actual task duration."
    }
 
def generate_schedule_recommendations(schedule: List[Dict]) -> List[str]:
    """Generate actionable recommendations based on schedule."""
    recommendations = []
    
    total_time = sum(t['duration_minutes'] for t in schedule)
    
    if total_time > 480:
        recommendations.append("⚠️ Schedule exceeds 8 hours. Consider splitting across multiple days.")
    
    if len(schedule) > 10:
        recommendations.append("📋 High task count. Group similar tasks to improve focus.")
    
    urgent_count = sum(1 for t in schedule if t.get('priority') == 'urgent')
    if urgent_count > 3:
        recommendations.append("🔥 Multiple urgent tasks detected. Prioritize ruthlessly.")
    
    if not recommendations:
        recommendations.append("✅ Schedule looks balanced and achievable!")
    
    return recommendations

# ─── NOTES ROUTES ─────────────────────────────────────────

@app.post("/notes", status_code=201)
def create_note(note: NoteCreateRequest, db: Session = Depends(get_db)):
    try:
        import json
        db_note = Note(
            title=note.title,
            content=note.content,
            tags=json.dumps(note.tags) if note.tags else "[]"
        )
        db.add(db_note)
        db.commit()
        db.refresh(db_note)
        return {
            "id": db_note.id,
            "title": db_note.title,
            "content": db_note.content,
            "tags": json.loads(db_note.tags) if db_note.tags else [],
            "created_at": db_note.created_at.isoformat() if db_note.created_at else None
        }
    except Exception as e:
        print(f"Note creation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/notes")
def get_all_notes(db: Session = Depends(get_db)):
    try:
        import json
        notes = db.query(Note).all()
        return [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content,
                "tags": json.loads(n.tags) if n.tags else [],
                "created_at": n.created_at.isoformat() if n.created_at else None
            }
            for n in notes
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/notes/{note_id}")
def get_note(note_id: int, db: Session = Depends(get_db)):
    import json
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return {
        "id": note.id,
        "title": note.title,
        "content": note.content,
        "tags": json.loads(note.tags) if note.tags else [],
        "created_at": note.created_at.isoformat() if note.created_at else None
    }

@app.put("/notes/{note_id}")
def update_note(note_id: int, note_update: NoteUpdateRequest, db: Session = Depends(get_db)):
    import json
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    try:
        if note_update.title is not None:
            note.title = note_update.title
        if note_update.content is not None:
            note.content = note_update.content
        if note_update.tags is not None:
            note.tags = json.dumps(note_update.tags)
        db.commit()
        db.refresh(note)
        return {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "tags": json.loads(note.tags) if note.tags else [],
            "status": "updated"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/notes/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(note)
    db.commit()
    return {"status": "success", "deleted_id": note_id}