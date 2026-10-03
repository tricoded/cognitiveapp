# app/ml/task_classifier.py

import re
from datetime import datetime, timedelta, date
from typing import Optional
from dataclasses import dataclass, field

# ─────────────────────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EisenhowerResult:
    quadrant: str               # "Q1" | "Q2" | "Q3" | "Q4"
    label: str                  # Human-readable label
    urgency_score: float        # 0.0 – 1.0
    importance_score: float     # 0.0 – 1.0
    recommended_action: str     # Do Now / Schedule / Delegate / Eliminate
    reasoning: list[str]        # Why this classification was given
    deadline_found: Optional[date] = None
    deadline_source: str = ""   # "symbol" | "nlp" | "due_date_field" | "none"
    confidence: float = 1.0     # 0.0 – 1.0


@dataclass
class ClassificationInput:
    notes: str                       = ""
    category: str                    = "Other"
    priority: str                    = "Medium"
    due_date: Optional[str]          = None     # ISO string or None
    canvas_activity: bool            = False    # User recently visited Canvas?
    tags: list[str]                  = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Symbol → Urgency Mapping
# ─────────────────────────────────────────────────────────────────────────────

URGENCY_SYMBOLS: dict[str, float] = {
    "!!!": 1.0,
    "!!":  0.85,
    "!":   0.7,
    "***": 1.0,
    "**":  0.8,
    "*":   0.6,
    "🔥":  1.0,
    "⚡":  0.9,
    "❗":  0.85,
    "‼️":  0.95,
    "🚨":  1.0,
    "📌":  0.5,
    "⏰":  0.8,
    "🗓️":  0.6,
}

# ─────────────────────────────────────────────────────────────────────────────
# NLP Deadline Patterns
# Detects phrases like "due friday", "by 5pm", "tomorrow", "in 2 days"
# ─────────────────────────────────────────────────────────────────────────────

_TODAY    = datetime.now().date
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

DEADLINE_PATTERNS: list[tuple[str, callable]] = [
    # "today", "tonight"
    (
        r"\b(today|tonight)\b",
        lambda _: datetime.now().date()
    ),
    # "tomorrow"
    (
        r"\btomorrow\b",
        lambda _: (datetime.now() + timedelta(days=1)).date()
    ),
    # "in X days"
    (
        r"\bin (\d+) days?\b",
        lambda m: (datetime.now() + timedelta(days=int(m.group(1)))).date()
    ),
    # "in X hours"
    (
        r"\bin (\d+) hours?\b",
        lambda m: datetime.now().date()
    ),
    # "this friday" / "next monday" etc.
    (
        r"\b(this|next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        lambda m: _next_weekday(m.group(2), offset=7 if m.group(1) == "next" else 0)
    ),
    # "by friday" / "due monday"
    (
        r"\b(?:by|due|before)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        lambda m: _next_weekday(m.group(1))
    ),
    # "by Jan 15" / "due March 3"
    (
        r"\b(?:by|due)\s+([a-zA-Z]+)\s+(\d{1,2})\b",
        lambda m: _parse_month_day(m.group(1), int(m.group(2)))
    ),
    # "dd/mm" or "mm/dd"
    (
        r"\b(\d{1,2})/(\d{1,2})\b",
        lambda m: _parse_slash_date(int(m.group(1)), int(m.group(2)))
    ),
    # "end of week"
    (
        r"\bend of (?:the )?week\b",
        lambda _: _next_weekday("friday")
    ),
    # "end of month"
    (
        r"\bend of (?:the )?month\b",
        lambda _: datetime.now().replace(day=28).date()
    ),
]


def _next_weekday(day_name: str, offset: int = 0) -> date:
    """Return the next occurrence of a weekday by name."""
    today     = datetime.now().date()
    target    = _WEEKDAYS.index(day_name.lower())
    current   = today.weekday()
    days_away = (target - current + 7) % 7 or 7
    return today + timedelta(days=days_away + offset)


def _parse_month_day(month_str: str, day: int) -> Optional[date]:
    """Parse 'January 15' → date object."""
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    month_num = months.get(month_str.lower())
    if not month_num:
        return None
    year = datetime.now().year
    try:
        return date(year, month_num, day)
    except ValueError:
        return None


def _parse_slash_date(a: int, b: int) -> Optional[date]:
    """Guess dd/mm or mm/dd — prefer dd/mm (UK/Australian style)."""
    year = datetime.now().year
    try:
        # Try dd/mm first
        return date(year, b, a)
    except ValueError:
        try:
            return date(year, a, b)
        except ValueError:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Importance Keywords by Category
# ─────────────────────────────────────────────────────────────────────────────

IMPORTANCE_KEYWORDS: dict[str, float] = {
    # High importance
    "exam":        1.0,
    "assignment":  0.9,
    "submission":  0.9,
    "deadline":    0.9,
    "quiz":        0.85,
    "presentation":0.85,
    "interview":   1.0,
    "report":      0.8,
    "project":     0.8,
    "thesis":      1.0,
    "dissertation":1.0,
    "test":        0.85,
    "assessment":  0.9,
    "grade":       0.85,
    "payment":     0.85,
    "invoice":     0.8,
    "legal":       0.9,
    "contract":    0.9,
    "meeting":     0.7,
    "review":      0.7,
    # Medium importance
    "email":       0.5,
    "call":        0.5,
    "read":        0.4,
    "research":    0.6,
    "notes":       0.4,
    # Low importance
    "clean":       0.3,
    "buy":         0.3,
    "watch":       0.2,
    "browse":      0.1,
    "optional":    0.1,
}

# ─────────────────────────────────────────────────────────────────────────────
# Priority String → Importance Score
# ─────────────────────────────────────────────────────────────────────────────

PRIORITY_TO_IMPORTANCE: dict[str, float] = {
    "critical": 1.0,
    "high":     0.8,
    "medium":   0.55,
    "low":      0.3,
    "none":     0.2,
}

# ─────────────────────────────────────────────────────────────────────────────
# Canvas Activity Signal → Urgency Boost
# If user was on Canvas recently → academic tasks get a +0.2 urgency bump
# ─────────────────────────────────────────────────────────────────────────────

CANVAS_CATEGORIES = {"academic", "study", "school", "university", "coursework"}
CANVAS_KEYWORDS   = {"assignment", "quiz", "exam", "submission", "canvas",
                     "moodle", "coursework", "lecture", "tutorial", "lab"}


# ─────────────────────────────────────────────────────────────────────────────
# Core Classifier
# ─────────────────────────────────────────────────────────────────────────────

class TaskClassifier:
    """
    Classifies tasks into Eisenhower Matrix quadrants using:
    1. Symbol-based urgency detection  (!, **, 🔥 etc.)
    2. NLP deadline extraction         (due friday, in 2 days, etc.)
    3. Due date field                  (ISO date from DB)
    4. Keyword importance scoring      (exam, interview, buy, browse...)
    5. Canvas activity signal          (user recently on Canvas portal)
    6. Priority field                  (Critical / High / Medium / Low)
    """

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def classify(self, task: ClassificationInput) -> EisenhowerResult:
        """
        Main entry point. Returns full Eisenhower classification.
        """
        full_text = f"{task.title} {task.notes}".lower()
        reasoning: list[str] = []

        # ── Step 1: Urgency Score ──────────────────────────────────────────
        urgency, deadline, deadline_source = self._compute_urgency(
            task, full_text, reasoning
        )

        # ── Step 2: Importance Score ───────────────────────────────────────
        importance = self._compute_importance(task, full_text, reasoning)

        # ── Step 3: Canvas boost ───────────────────────────────────────────
        if task.canvas_activity:
            text_words = set(full_text.split())
            if (
                task.category.lower() in CANVAS_CATEGORIES
                or bool(text_words & CANVAS_KEYWORDS)
            ):
                urgency = min(1.0, urgency + 0.2)
                reasoning.append(
                    "🎓 Canvas activity detected — academic urgency boosted"
                )

        # ── Step 4: Map to quadrant ────────────────────────────────────────
        quadrant, label, action, confidence = self._assign_quadrant(
            urgency, importance, reasoning
        )

        return EisenhowerResult(
            quadrant=quadrant,
            label=label,
            urgency_score=round(urgency, 2),
            importance_score=round(importance, 2),
            recommended_action=action,
            reasoning=reasoning,
            deadline_found=deadline,
            deadline_source=deadline_source,
            confidence=round(confidence, 2),
        )

    def batch_classify(
        self, tasks: list[ClassificationInput]
    ) -> list[EisenhowerResult]:
        """Classify a list of tasks and return sorted by urgency × importance."""
        results = [self.classify(t) for t in tasks]
        return sorted(
            results,
            key=lambda r: r.urgency_score * r.importance_score,
            reverse=True
        )

    def classify_from_dict(self, task_dict: dict) -> EisenhowerResult:
        """Convenience wrapper — accepts raw dict from DB/API."""
        return self.classify(ClassificationInput(
            title           = task_dict.get("title", ""),
            notes           = task_dict.get("notes", ""),
            category        = task_dict.get("category", "Other"),
            priority        = task_dict.get("priority", "Medium"),
            due_date        = task_dict.get("due_date"),
            canvas_activity = task_dict.get("canvas_activity", False),
            tags            = task_dict.get("tags", []),
        ))

    # ─────────────────────────────────────────────────────────────────────
    # Urgency Computation
    # ─────────────────────────────────────────────────────────────────────

    def _compute_urgency(
        self,
        task: ClassificationInput,
        full_text: str,
        reasoning: list[str],
    ) -> tuple[float, Optional[date], str]:
        """
        Returns (urgency_score, deadline_date, deadline_source).
        Sources tried in order:
          1. Symbol detection in title/notes
          2. NLP pattern matching in title/notes
          3. due_date field from DB
        """
        urgency         = 0.3   # baseline
        deadline        = None
        deadline_source = "none"

        # ── Symbol detection ──
        symbol_urgency = self._detect_symbols(task.title + " " + task.notes)
        if symbol_urgency > urgency:
            urgency = symbol_urgency
            reasoning.append(f"⚡ Urgency symbol detected (score: {symbol_urgency:.1f})")

        # ── NLP deadline extraction ──
        nlp_deadline = self._extract_deadline_nlp(full_text)
        if nlp_deadline:
            deadline        = nlp_deadline
            deadline_source = "nlp"
            days_away       = (nlp_deadline - datetime.now().date()).days

            nlp_urgency = self._deadline_to_urgency(days_away)
            if nlp_urgency > urgency:
                urgency = nlp_urgency
            reasoning.append(
                f"📅 Deadline found in text: {nlp_deadline} "
                f"({days_away}d away → urgency {nlp_urgency:.1f})"
            )

        # ── due_date field from DB ──
        if task.due_date:
            try:
                due = datetime.fromisoformat(
                    task.due_date.replace("Z", "+00:00")
                ).date()
                days_away    = (due - datetime.now().date()).days
                field_urgency = self._deadline_to_urgency(days_away)

                if not deadline or field_urgency > urgency:
                    # Prefer the more urgent deadline
                    deadline        = due
                    deadline_source = "due_date_field"
                    urgency         = max(urgency, field_urgency)
                    reasoning.append(
                        f"📆 Due date field: {due} "
                        f"({days_away}d away → urgency {field_urgency:.1f})"
                    )
            except (ValueError, AttributeError):
                pass

        return urgency, deadline, deadline_source

    def _detect_symbols(self, text: str) -> float:
        """Scan text for urgency symbols, return highest match."""
        max_score = 0.0
        for symbol, score in URGENCY_SYMBOLS.items():
            if symbol in text:
                max_score = max(max_score, score)
        return max_score

    def _extract_deadline_nlp(self, text: str) -> Optional[date]:
        """Try each regex pattern in order, return first match."""
        for pattern, resolver in DEADLINE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    result = resolver(match)
                    if result:
                        return result
                except Exception:
                    continue
        return None

    def _deadline_to_urgency(self, days_away: int) -> float:
        """Convert days until deadline into urgency score."""
        if days_away <= 0:   return 1.0   # overdue
        if days_away == 1:   return 0.95
        if days_away <= 2:   return 0.9
        if days_away <= 3:   return 0.8
        if days_away <= 5:   return 0.7
        if days_away <= 7:   return 0.6
        if days_away <= 14:  return 0.45
        if days_away <= 30:  return 0.35
        return 0.2

    # ─────────────────────────────────────────────────────────────────────
    # Importance Computation
    # ─────────────────────────────────────────────────────────────────────

    def _compute_importance(
        self,
        task: ClassificationInput,
        full_text: str,
        reasoning: list[str],
    ) -> float:
        """
        Importance from:
          1. Priority field
          2. Keyword scanning in title + notes
          3. Category bonus
        """
        # Base: priority field
        importance = PRIORITY_TO_IMPORTANCE.get(task.priority.lower(), 0.55)
        reasoning.append(f"📊 Priority field '{task.priority}' → importance {importance:.1f}")

        # Keyword scan
        keyword_scores = []
        for keyword, score in IMPORTANCE_KEYWORDS.items():
            if keyword in full_text:
                keyword_scores.append(score)

        if keyword_scores:
            keyword_importance = max(keyword_scores)
            # Blend: take the higher of priority-based or keyword-based
            if keyword_importance > importance:
                importance = (importance + keyword_importance) / 2 + 0.1
                importance = min(1.0, importance)
                reasoning.append(
                    f"🔑 Importance keyword detected → boosted to {importance:.1f}"
                )

        return round(importance, 2)

    # ─────────────────────────────────────────────────────────────────────
    # Quadrant Assignment
    # ─────────────────────────────────────────────────────────────────────

    def _assign_quadrant(
        self,
        urgency: float,
        importance: float,
        reasoning: list[str],
    ) -> tuple[str, str, str, float]:
        """
        Returns (quadrant, label, recommended_action, confidence).

        Classic 2×2 Eisenhower Matrix:
        ┌─────────────────────┬──────────────────────┐
        │  Q1: Urgent+Imp     │  Q2: Not Urgent+Imp  │
        │  → Do Now           │  → Schedule          │
        ├─────────────────────┼──────────────────────┤
        │  Q3: Urgent+Not Imp │  Q4: Neither         │
        │  → Delegate         │  → Eliminate         │
        └─────────────────────┴──────────────────────┘
        """
        # Threshold: 0.6 = "high"
        high_urgency    = urgency    >= 0.6
        high_importance = importance >= 0.6

        # Calculate confidence: how far from the threshold?
        dist_urgency    = abs(urgency    - 0.6)
        dist_importance = abs(importance - 0.6)
        confidence      = min(1.0, 0.5 + (dist_urgency + dist_importance) / 2)

        if high_urgency and high_importance:
            reasoning.append("🔴 Q1: High urgency + High importance")
            return "Q1", "Do Now", "Do it immediately", confidence

        elif not high_urgency and high_importance:
            reasoning.append("🟡 Q2: Low urgency + High importance")
            return "Q2", "Schedule", "Plan a focused time block", confidence

        elif high_urgency and not high_importance:
            reasoning.append("🟠 Q3: High urgency + Low importance")
            return "Q3", "Delegate", "Delegate or batch with others", confidence

        else:
            reasoning.append("⚪ Q4: Low urgency + Low importance")
            return "Q4", "Eliminate", "Drop it or do only if time allows", confidence
