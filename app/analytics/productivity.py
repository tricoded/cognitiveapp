from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Task, SkillEvidence
from datetime import datetime
from typing import Dict, Any
 
 
def calculate_estimation_accuracy(task: Task) -> float:
    """Returns accuracy percentage (100% = perfect)"""
    if not task.actual_minutes or not task.estimated_minutes:
        return 0.0
    return (task.estimated_minutes / task.actual_minutes) * 100
 
 
def get_estimation_analytics(db: Session) -> Dict[str, Any]:
    """Brutal truth about estimation skills by category"""
    completed_tasks = db.query(Task).filter(
        Task.status == "completed",
        Task.actual_minutes.isnot(None),
        Task.estimated_minutes.isnot(None)
    ).all()
    
    if not completed_tasks:
        return {
            "message": "No completed tasks with time tracking yet.",
            "total_tasks": 0
        }
    
    # Group by category
    by_category = {}
    for task in completed_tasks:
        cat = task.category
        if cat not in by_category:
            by_category[cat] = {"estimates": [], "actuals": []}
        
        by_category[cat]["estimates"].append(task.estimated_minutes)
        by_category[cat]["actuals"].append(task.actual_minutes)
    
    # Calculate stats per category
    results = {}
    for cat, data in by_category.items():
        avg_estimate = sum(data["estimates"]) / len(data["estimates"])
        avg_actual = sum(data["actuals"]) / len(data["actuals"])
        multiplier = avg_actual / avg_estimate if avg_estimate > 0 else 0
        
        # Generate verdict
        if multiplier < 0.8:
            verdict = f"You OVERESTIMATE '{cat}' by {(1-multiplier)*100:.0f}%"
        elif multiplier > 1.5:
            verdict = f"You UNDERESTIMATE '{cat}'. Multiply by {multiplier:.1f}x"
        elif 0.9 <= multiplier <= 1.1:
            verdict = f"[OK] '{cat}' estimates are accurate"
        else:
            verdict = f"Off by {abs(1-multiplier)*100:.0f}%"
        
        results[cat] = {
            "task_count": len(data["estimates"]),
            "avg_estimate_min": round(avg_estimate, 1),
            "avg_actual_min": round(avg_actual, 1),
            "multiplier": round(multiplier, 2),
            "verdict": verdict
        }
    
    # Find worst category
    worst = max(results.items(), key=lambda x: abs(x[1]["multiplier"] - 1.0))
    
    return {
        "total_tasks": len(completed_tasks),
        "by_category": results,
        "recommendation": f"Focus on '{worst[0]}' - Use {worst[1]['multiplier']:.1f}x multiplier"
    }
 
 
def get_productivity_by_hour(db: Session) -> Dict[str, Any]:
    """When are you ACTUALLY productive?"""
    completed_tasks = db.query(Task).filter(
        Task.status == "completed",
        Task.completed_at.isnot(None)
    ).all()
    
    if len(completed_tasks) < 5:
        return {
            "message": f"Need 5+ completed tasks. You have {len(completed_tasks)}.",
            "by_hour": {}
        }
    
    # Group by hour
    by_hour = {}
    for task in completed_tasks:
        hour = task.completed_at.hour
        if hour not in by_hour:
            by_hour[hour] = {
                "count": 0,
                "energy": [],
                "distractions": []
            }
        
        by_hour[hour]["count"] += 1
        if task.energy_level_start:
            by_hour[hour]["energy"].append(task.energy_level_start)
        by_hour[hour]["distractions"].append(task.distraction_count)
    
    # Calculate stats
    results = {}
    for hour, data in by_hour.items():
        avg_energy = sum(data["energy"]) / len(data["energy"]) if data["energy"] else None
        avg_dist = sum(data["distractions"]) / len(data["distractions"])
        
        # Verdict
        if data["count"] >= 5:
            verdict = "[PEAK]"
        elif data["count"] >= 3:
            verdict = "[GOOD]"
        else:
            verdict = "[LOW]"
        
        results[f"{hour:02d}:00"] = {
            "tasks_completed": data["count"],
            "avg_energy": round(avg_energy, 1) if avg_energy else None,
            "avg_distractions": round(avg_dist, 1),
            "status": verdict
        }
    
    # Find top hours
    sorted_hours = sorted(by_hour.items(), key=lambda x: x[1]["count"], reverse=True)
    top_3 = sorted_hours[:3]
    
    return {
        "by_hour": results,
        "peak_hours": [f"{h[0]:02d}:00" for h in top_3],
        "recommendation": f"Schedule deep work at {top_3[0][0]:02d}:00"
    }
 
 
def get_skill_inventory(db: Session) -> Dict[str, Any]:
    """What can you ACTUALLY do?"""
    skills = db.query(
        SkillEvidence.skill_name,
        func.count(SkillEvidence.id).label("count"),
        func.avg(SkillEvidence.quality_score).label("avg_quality"),
        func.avg(SkillEvidence.time_taken).label("avg_time")
    ).group_by(SkillEvidence.skill_name).all()
    
    if not skills:
        return {
            "message": "No skills recorded yet.",
            "skills": {}
        }
    
    results = {}
    for skill in skills:
        # Determine level
        if skill.count < 3:
            level = "Beginner"
            status = f"[UNVERIFIED] Only {skill.count} proven task(s)"
        elif skill.count < 10:
            if skill.avg_quality > 0.7:
                level = "Intermediate"
                status = f"[VERIFIED] {skill.count} tasks at {skill.avg_quality*100:.0f}%"
            else:
                level = "Developing"
                status = f"[WARNING] {skill.count} tasks, quality {skill.avg_quality*100:.0f}%"
        else:
            if skill.avg_quality > 0.8:
                level = "Advanced"
                status = f"[EXPERT] {skill.count} tasks at {skill.avg_quality*100:.0f}%"
            else:
                level = "Intermediate"
                status = f"[OK] {skill.count} tasks, improve quality"
        
        results[skill.skill_name] = {
            "evidence_count": skill.count,
            "avg_quality_pct": round(skill.avg_quality * 100, 1),
            "avg_time_min": round(skill.avg_time, 1) if skill.avg_time else None,
            "level": level,
            "status": status
        }
    
    return {"skills": results}
 
 
def get_time_of_day_category() -> str:
    """Helper: Categorize current time"""
    hour = datetime.now().hour
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"