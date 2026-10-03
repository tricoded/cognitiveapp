# app/ml/task_predictor.py

import pickle
import logging
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_PATH = Path("app/ml/models/time_predictor.pkl")

# Feature encoding maps
PRIORITY_MAP = {"Critical": 5, "High": 4, "Medium": 3, "Low": 2, "Overdue": 6}
CATEGORY_MAP = {
    "Development": 5,
    "Work":        4,
    "Learning":    3,
    "Personal":    2,
    "Finance":     1,
}

FEATURE_NAMES = [
    "estimated_minutes",
    "title_word_count",
    "priority_score",
    "category_score",
    "hour_created",
    "has_deadline",
    "days_until_due",
]


class TaskDifficultyPredictor:
    """
    Predicts how long a task will actually take (in minutes).

    Training:   GradientBoostingRegressor on completed tasks with actual_minutes.
    Evaluation: time-ordered CV (train on earlier completions, test on later),
                compared against the naive baseline "actual = my own estimate".
    Fallback:   Returns task.estimated_minutes if not trained, or 60 if neither.
    Auto-trains: After every 5th task completion via retrain_if_ready().
    """

    def __init__(self):
        self.model        = None
        self.is_trained   = False
        self.last_metrics = {}
        self._load()

    # ── Persistence ────────────────────────────────────────────────────
    def _load(self):
        if MODEL_PATH.exists():
            try:
                with open(MODEL_PATH, "rb") as f:
                    saved = pickle.load(f)
                # Older pickles stored a bare model with a different feature set.
                if isinstance(saved, dict) and saved.get("features") == FEATURE_NAMES:
                    self.model        = saved["model"]
                    self.last_metrics = saved.get("metrics", {})
                    self.is_trained   = True
                    logger.info("[Predictor] Model loaded from disk.")
                else:
                    logger.info("[Predictor] Stale model format on disk; will retrain.")
            except Exception as e:
                logger.warning(f"[Predictor] Failed to load model: {e}")

    def _save(self):
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({"model": self.model, "features": FEATURE_NAMES, "metrics": self.last_metrics}, f)

    # ── Feature Engineering ─────────────────────────────────────────────
    def _featurize(self, task) -> list[float]:
        """
        Convert a task object into a numeric feature vector (see FEATURE_NAMES).
        The user's own estimate is the strongest signal; the model learns how
        that estimate is biased for different kinds of task.
        """
        estimated    = float(task.estimated_minutes or 60)
        title_words  = len((task.title or "").split())
        priority     = PRIORITY_MAP.get(task.priority or "Medium", 3)
        category     = CATEGORY_MAP.get(task.category or "Work", 4)
        hour_created = task.created_at.hour if task.created_at else 9
        has_deadline = 1 if task.due_date else 0

        # Days until due (0 if overdue, 30 if no deadline)
        days_until_due = 30
        if task.due_date:
            due = task.due_date.date() if hasattr(task.due_date, "date") else task.due_date
            days_until_due = max(0, (due - date.today()).days)

        return [
            estimated,
            title_words,
            priority,
            category,
            hour_created,
            has_deadline,
            days_until_due,
        ]

    # ── Training ────────────────────────────────────────────────────────
    def train(self, completed_tasks: list) -> bool:
        """
        Train on completed tasks that have actual_minutes recorded.
        Returns True if training succeeded, False if not enough data.
        """
        try:
            from sklearn.base import clone
            from sklearn.ensemble import GradientBoostingRegressor
            from sklearn.model_selection import TimeSeriesSplit
            import numpy as np
        except ImportError:
            logger.error("[Predictor] scikit-learn not installed. Run: pip install scikit-learn")
            return False

        # Only train on tasks with real time data
        trainable = [
            t for t in completed_tasks
            if t.actual_minutes and t.actual_minutes > 0
        ]

        if len(trainable) < 5:
            logger.info(f"[Predictor] Not enough data: {len(trainable)}/5 tasks needed.")
            return False

        # Order by completion time so CV folds never train on the future.
        def _when(t):
            for attr in ("completed_at", "created_at"):
                v = getattr(t, attr, None)
                if isinstance(v, datetime):
                    return v
            return datetime.min
        trainable.sort(key=_when)

        X = [self._featurize(t) for t in trainable]
        y = [float(t.actual_minutes) for t in trainable]

        self.model = GradientBoostingRegressor(
            n_estimators  = 100,
            max_depth     = 3,
            learning_rate = 0.1,
            subsample     = 0.8,
            random_state  = 42,
        )
        self.model.fit(X, y)
        self.is_trained = True

        self.last_metrics = {
            "samples_used": len(trainable),
            "trained_at":   datetime.utcnow().isoformat(),
        }
        # Time-ordered CV vs the "trust my own estimate" baseline
        if len(trainable) >= 10:
            Xa, ya = np.array(X), np.array(y)
            tscv = TimeSeriesSplit(n_splits=min(5, len(trainable) // 3))
            model_err, base_err = [], []
            for tr, te in tscv.split(Xa):
                m = clone(self.model).fit(Xa[tr], ya[tr])
                model_err.append(np.abs(m.predict(Xa[te]) - ya[te]).mean())
                base_err.append(np.abs(Xa[te, 0] - ya[te]).mean())
            self.last_metrics["mae_minutes"]          = round(float(np.mean(model_err)), 1)
            self.last_metrics["baseline_mae_minutes"] = round(float(np.mean(base_err)), 1)
            logger.info(
                f"[Predictor] Trained on {len(trainable)} tasks. "
                f"Time-CV MAE {self.last_metrics['mae_minutes']} min vs own-estimate "
                f"{self.last_metrics['baseline_mae_minutes']} min"
            )
        else:
            logger.info(f"[Predictor] Trained on {len(trainable)} tasks (too few for CV).")

        self._save()
        return True

    # ── Prediction ──────────────────────────────────────────────────────
    def predict(self, task) -> int:
        """
        Returns predicted minutes for a single task.
        Falls back to estimated_minutes → 60 if model not ready.
        """
        if not self.is_trained or self.model is None:
            return task.estimated_minutes or 60

        try:
            features = self._featurize(task)
            raw      = self.model.predict([features])[0]
            # Round to nearest 5 minutes, minimum 5
            return max(5, int(round(raw / 5) * 5))
        except Exception as e:
            logger.warning(f"[Predictor] Prediction failed: {e}")
            return task.estimated_minutes or 60

    predict_single = predict

    # ── API helpers (used by /ml/* routes) ──────────────────────────────
    def train_report(self, completed_tasks: list) -> dict:
        if not self.train(completed_tasks):
            n = len([t for t in completed_tasks if t.actual_minutes and t.actual_minutes > 0])
            return {"status": "skipped", "ml_enabled": False, "samples_used": n,
                    "reason": f"Need at least 5 completed tasks with tracked time (have {n})."}
        return {
            "status":       "trained",
            "ml_enabled":   True,
            "samples_used": self.last_metrics.get("samples_used"),
            "mae_minutes":  self.last_metrics.get("mae_minutes"),
            "trained_at":   self.last_metrics.get("trained_at"),
        }

    def predict_duration(self, fields: dict) -> dict:
        task = SimpleNamespace(
            title=fields.get("title", ""),
            priority=fields.get("priority", "Medium"),
            category=fields.get("category", "Other"),
            estimated_minutes=fields.get("estimated_minutes", 60),
            created_at=datetime.now(),
            due_date=None,
        )
        predicted = self.predict(task)
        est = task.estimated_minutes or 60
        diff = predicted - est
        insight = (
            "Matches your estimate" if abs(diff) < 5 else
            f"Likely {abs(diff)} min {'longer' if diff > 0 else 'shorter'} than you estimated"
        )
        return {
            "predicted_minutes":        predicted,
            "predicted_actual_minutes": predicted,   # key used by /plan/ml
            "your_estimate":            est,
            "insight":                  insight,
            "ml_enabled":               self.is_trained,
        }

    def get_status(self) -> dict:
        return {"ml_enabled": self.is_trained, "features": FEATURE_NAMES, **self.last_metrics}

    def get_feature_importance(self) -> Optional[dict]:
        if not self.is_trained or not hasattr(self.model, "feature_importances_"):
            return None
        imp = {n: round(float(v), 4) for n, v in zip(FEATURE_NAMES, self.model.feature_importances_)}
        return dict(sorted(imp.items(), key=lambda kv: -kv[1]))

    # ── Auto-retrain trigger ─────────────────────────────────────────────
    def retrain_if_ready(self, db) -> bool:
        """
        Called after every task completion.
        Retrains automatically when we have 5, 10, 20, 50+ completions
        (threshold-based so it doesn't retrain on every single task).
        """
        from app.models import Task

        completed = db.query(Task).filter(
            Task.status == "completed",
            Task.actual_minutes.isnot(None),
        ).all()

        count = len(completed)

        # Retrain at: 5, 10, 20, then every 10 after that
        thresholds = {5, 10, 20}
        should_retrain = (
            count in thresholds or
            (count >= 20 and count % 10 == 0)
        )

        if should_retrain:
            success = self.train(completed)
            if success:
                logger.info(f"[Predictor] Auto-retrained at {count} completions.")
            return success

        return False


# ── Singleton ────────────────────────────────────────────────────────────────
predictor = TaskDifficultyPredictor()
