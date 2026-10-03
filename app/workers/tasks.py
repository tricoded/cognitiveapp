from celery import Celery
import json
import os

# Import will work after we create the ML files
# from app.ml.task_predictor import TaskDifficultyPredictor
from app.database import SessionLocal
from app.models import Task

# Use environment variable for Redis URL
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery('cognitive', broker=REDIS_URL)

@celery_app.task
def retrain_ml_model():
    """Background task to retrain ML model daily."""
    db = SessionLocal()
    
    try:
        # Fetch completed tasks
        tasks = db.query(Task).filter(Task.status == "completed").all()
        
        # Transform to dict format
        task_data = []
        for task in tasks:
            if task.actual_minutes:  # Only include tasks with completion data
                task_data.append({
                    'priority': task.priority,
                    'category': task.category,
                    'estimated_minutes': task.estimated_minutes,
                    'actual_minutes': task.actual_minutes,
                    'distraction_count': task.distraction_count or 0,
                    'energy_level_start': task.energy_level_start or 5,
                })
        
        # Retrain model (uncomment when TaskDifficultyPredictor is created)
        # predictor = TaskDifficultyPredictor()
        # predictor.train(task_data)
        
        print(f"✓ ML model retrained with {len(task_data)} tasks")
        
    finally:
        db.close()
    
@celery_app.task
def generate_daily_insights(user_id: str):
    """Generate and cache daily productivity insights."""
    db = SessionLocal()
    
    try:
        # Import here to avoid circular imports
        from app.analytics.insights import ProductivityAnalyzer
        from app.cache.redis_cache import cache
        
        analyzer = ProductivityAnalyzer(db)
        insights = analyzer.calculate_efficiency_score(user_id)
        
        # Store in Redis for quick access
        cache.set(f"insights:{user_id}", insights, ttl=86400)
        
        print(f"✓ Generated insights for user {user_id}")
        
    finally:
        db.close()

# Celery beat schedule (runs tasks periodically)
celery_app.conf.beat_schedule = {
    'retrain-ml-daily': {
        'task': 'app.workers.tasks.retrain_ml_model',
        'schedule': 86400.0,  # Every 24 hours
    },
}
