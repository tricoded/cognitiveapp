import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List

class ProductivityAnalyzer:
    """Advanced analytics for productivity patterns."""
    
    def __init__(self, db):
        self.db = db
        
    def calculate_efficiency_score(self, user_id: str) -> Dict:
        """Calculate overall productivity efficiency."""
        tasks = self.db.query(Task).filter(
            Task.status == "completed",
            Task.completed_at >= datetime.utcnow() - timedelta(days=30)
        ).all()
        
        if not tasks:
            return {"score": 0, "insights": []}
        
        # Convert to DataFrame for analysis
        df = pd.DataFrame([{
            'estimated': t.estimated_minutes,
            'actual': t.actual_minutes,
            'priority': t.priority,
            'hour': t.completed_at.hour,
            'weekday': t.completed_at.weekday(),
            'energy_start': t.energy_level_start,
            'energy_end': t.energy_level_end,
        } for t in tasks])
        
        # Calculate metrics
        accuracy = 1 - (abs(df['estimated'] - df['actual']) / df['estimated']).mean()
        energy_drop = (df['energy_start'] - df['energy_end']).mean()
        completion_rate = len(tasks) / 30  # Tasks per day
        
        # Find optimal hours
        hourly_productivity = df.groupby('hour').agg({
            'actual': 'sum',
            'energy_end': 'mean'
        })
        best_hours = hourly_productivity.nlargest(3, 'energy_end').index.tolist()
        
        return {
            "efficiency_score": float(accuracy * 100),
            "avg_tasks_per_day": float(completion_rate),
            "energy_drop_per_task": float(energy_drop),
            "best_hours": [f"{h}:00" for h in best_hours],
            "insights": self._generate_insights(df, accuracy, energy_drop)
        }
    
    def _generate_insights(self, df: pd.DataFrame, accuracy: float, energy_drop: float) -> List[str]:
        """AI-powered insights generation."""
        insights = []
        
        if accuracy < 0.7:
            insights.append("⚠️ You're underestimating task durations by 30%. Add 50% buffer time.")
        
        if energy_drop > 3:
            insights.append("🔋 High energy drain detected. Take more breaks between tasks.")
        
        # Detect procrastination patterns
        evening_tasks = len(df[df['hour'] >= 18])
        if evening_tasks > len(df) * 0.4:
            insights.append("🌙 40% of work done after 6pm. Consider morning-focused schedule.")
        
        return insights
    
    def predict_burnout_risk(self) -> Dict:
        """Predict burnout risk using recent patterns."""
        recent_tasks = self.db.query(Task).filter(
            Task.completed_at >= datetime.utcnow() - timedelta(days=7)
        ).all()
        
        # Calculate burnout indicators
        avg_daily_hours = sum(t.actual_minutes for t in recent_tasks) / (7 * 60)
        weekend_work = len([t for t in recent_tasks if t.completed_at.weekday() >= 5])
        
        risk_score = 0
        if avg_daily_hours > 10: risk_score += 40
        if weekend_work > 5: risk_score += 30
        if avg_daily_hours < 2: risk_score += 20  # Procrastination indicator
        
        return {
            "burnout_risk": min(risk_score, 100),
            "avg_daily_hours": round(avg_daily_hours, 1),
            "weekend_work_count": weekend_work,
            "recommendation": self._get_burnout_recommendation(risk_score)
        }
    
    def _get_burnout_recommendation(self, risk: int) -> str:
        if risk > 70:
            return "🚨 High burnout risk! Schedule a full day off this week."
        elif risk > 40:
            return "⚠️ Moderate risk. Reduce daily hours to 8 and avoid weekend work."
        else:
            return "✅ Healthy work pattern. Keep it up!"
