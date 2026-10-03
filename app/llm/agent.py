# app/llm/agent.py
import httpx
import os
import re
import logging
from datetime import datetime, date, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.models import Task
from app.ml.task_predictor import predictor  # shared singleton (same model as /ml/* routes)
from app.ml.intent_classifier import intent_clf
from app.ml.user_patterns import (
    analyze_user_patterns,
    adjust_plan_for_user,
    get_personalized_insights,
    get_cached_patterns,
)
from app.ml.streaks import get_streak

logger = logging.getLogger(__name__)

# ── Ollama Config ──────────────────────────────────────────────────────────
OLLAMA_HOST     = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT     = os.getenv("OLLAMA_PORT", "11434")
OLLAMA_BASE_URL = (
    OLLAMA_HOST if OLLAMA_HOST.startswith("http")
    else f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

PRIORITY_EMOJI = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢", "Overdue": "🚨"}
STATUS_EMOJI   = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}


# ══════════════════════════════════════════════════════════════════════════════
#  STRIP MARKDOWN
# ══════════════════════════════════════════════════════════════════════════════

def strip_markdown(text: str) -> str:
    if not text:
        return text
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'_{1,3}(.+?)_{1,3}',   r'\1', text, flags=re.DOTALL)
    text = re.sub(r'`(.+?)`', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'^\s*>\s?', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ══════════════════════════════════════════════════════════════════════════════
#  INTENT PATTERNS
# ══════════════════════════════════════════════════════════════════════════════

INTENT_PATTERNS = {
    "help": [
        r"\bhelp\b",
        r"\bwhat can you do\b",
        r"\bhow do i\b",
        r"\bcommands?\b",
        r"\bhow does this work\b",
    ],
    "create_task": [
        r"\b(add|create|make|new|set up|schedule)\b.*\btask\b",
        r"\btask\b.*\b(add|create|make|new)\b",
        r"\bremind me to\b",
        r"\bi need to\b",
        r"\bput\b.*\bon my list\b",
        r"\bi have to\b",
        r"\bdon'?t forget to\b",
    ],
    "list_tasks": [
        r"\b(show|list|what|display|give me|get)\b.*\btasks?\b",
        r"\btasks?\b.*\b(do i have|pending|remaining|left|today|week)\b",
        r"\bwhat.*(do i have|am i working on)\b",
        r"\bmy (todo|to-do|task list|workload)\b",
    ],
    "complete_task": [
        # ✅ FIX: Added \s* so "complete task16" (no space) works
        r"\bcomplete\s*task\s*#?\d+",
        r"\bmark\s*task\s*#?\d+",
        r"\b(done|finished|completed|finish|complete|mark.*done)\b.*\btask\b",
        r"\btask\s*#?\d+.*\b(done|finished|completed)\b",
        r"\bi (finished|completed|did)\b",
    ],
    "set_priority": [
        r"\bset\b.*\btask\b.*\bpriority\b",
        r"\bset\b.*\bpriority\b.*\btask\b",
        r"\bchange\b.*\bpriority\b",
        r"\bupdate\b.*\bpriority\b",
        r"\btask\b.*\bpriority\b.*(to|as)\b",
        r"\bmark\b.*\btask\b.*(high|low|medium|critical)\b",
        r"\bpriority.*to\b",
    ],
    "bulk_set_priority": [
        r"\bset\b.*\btasks?\b.*#\d+.*#\d+",
        r"\bupdate\b.*\btasks?\b.*#\d+.*#\d+",
    ],
    "review_priorities": [
        r"\breview\b.*\bpriorities\b",
        r"\bpriorities\b.*\breview\b",
        r"\bset all priorities\b",
        r"\bfix.*priorities\b",
        r"\bprioritize.*tasks\b",
        r"\bprioritize my\b",
    ],
    "task_analytics": [
        r"\b(how|what).*(productive|productivity|performing|accuracy)\b",
        r"\b(stats|statistics|analytics|report|insights?|trends?)\b",
        r"\bhow (am i|have i been)\b",
        r"\bmy (performance|progress|week|month)\b",
        r"\bshow.*stats\b",
    ],
    "task_predict": [
        r"\bhow long\b",
        r"\b(estimate|predict|guess)\b.*\btask\b",
        r"\bwill.*take\b",
        r"\btime estimate\b",
    ],
    "get_plan": [
        r"\b(plan|schedule|organize)\b.*\b(my day|today|tasks?)\b",
        r"\bwhat should i (do|work on|tackle|start)\b",
        r"\b(best order|optimal|most important)\b",
        r"\bplan my day\b",
        r"\bmy day\b",
    ],
    # ✅ NEW: Previously missing intents that caused fallback
    "procrastination": [
        r"\bprocrastinat\w*\b",
        r"\bavoid\w*\b.*\btask\b",
        r"\bkeep skipping\b",
        r"\bbeen putting off\b",
        r"\bhaven'?t done\b",
        r"\bbeen delay\w*\b",
        r"\bwhat.*avoiding\b",
    ],
    "goal_check": [
        r"\bdaily goal\b",
        r"\bon track\b",
        r"\bgoal (check|progress|status)\b",
        r"\bam i on track\b",
        r"\bhitting my goal\b",
        r"\bgoal.*today\b",
    ],
    "category_breakdown": [
        r"\bcategor\w+\b.*\b(time|most|spend)\b",
        r"\b(spend|spent).*\btime\b.*\bcategor\w+\b",
        r"\bmost time on\b",
        r"\btime breakdown\b",
        r"\bby category\b",
        r"\bwhich category\b",
    ],
    "general_chat": [],
}


# ══════════════════════════════════════════════════════════════════════════════
#  INTENT DETECTION — single definition (Bug 1 fixed: removed duplicate)
# ══════════════════════════════════════════════════════════════════════════════

def detect_intent(message: str) -> str:
    # 1. ML classifier first
    if intent_clf.is_trained:
        intent, confidence = intent_clf.predict(message)
        logger.info(f"[ML Intent] {intent} ({confidence:.2f})")
        if confidence >= 0.45:
            return intent

    # 2. Regex fallback — check bulk before set (more specific first)
    msg_lower = message.lower()
    priority_order = [
        "bulk_set_priority", "set_priority", "review_priorities",
        "complete_task", "create_task", "list_tasks", "get_plan",
        "task_analytics", "task_predict", "help",
        "procrastination", "goal_check", "category_breakdown",
    ]
    for intent in priority_order:
        for pattern in INTENT_PATTERNS.get(intent, []):
            if re.search(pattern, msg_lower):
                return intent

    # 3. Fuzzy keyword scoring — ✅ FIX: removed "how" from analytics,
    #    added "complete" score boost to fix "complete task16" routing
    scores = {
        "create_task":       sum(msg_lower.count(w) for w in ["add", "todo", "need", "create", "remind"]),
        "complete_task":     sum(msg_lower.count(w) for w in ["done", "complete", "finished", "completed", "mark"]),
        "list_tasks":        sum(msg_lower.count(w) for w in ["list", "show", "pending", "see", "view"]),
        "get_plan":          sum(msg_lower.count(w) for w in ["plan", "day", "schedule", "today", "focus"]),
        "task_analytics":    sum(msg_lower.count(w) for w in ["stats", "streak", "progress", "analytics"]),
        "set_priority":      sum(msg_lower.count(w) for w in ["priority", "urgent", "critical", "review"]),
        "delete_task":       sum(msg_lower.count(w) for w in ["delete", "remove", "cancel"]),
        "procrastination":   sum(msg_lower.count(w) for w in ["procrastinat", "avoiding", "skipping", "putting off"]),
        "goal_check":        sum(msg_lower.count(w) for w in ["goal", "track", "target"]),
        "category_breakdown":sum(msg_lower.count(w) for w in ["category", "spend", "time on"]),
    }

    # ✅ FIX: "complete task16" — if "complete" AND a digit exists, force complete_task
    if re.search(r'\bcomplete\s*\w*\s*\d+', msg_lower):
        return "complete_task"

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        logger.info(f"[Intent] Fuzzy → {best} (score: {scores[best]})")
        return best

    return "general_chat"


# ══════════════════════════════════════════════════════════════════════════════
#  PRIORITY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def compute_auto_priority(task) -> str:
    if not task.due_date:
        return task.priority or "Medium"
    today     = date.today()
    due       = task.due_date.date() if hasattr(task.due_date, "date") else task.due_date
    days_left = (due - today).days
    if days_left < 0:   return "Overdue"
    elif days_left <= 1: return "Critical"
    elif days_left <= 3: return "High"
    elif days_left <= 7: return "Medium"
    else:                return "Low"


def resolve_priority(task) -> str:
    auto   = compute_auto_priority(task)
    order  = {"Overdue": 0, "Critical": 1, "High": 2, "Medium": 3, "Low": 4}
    stored = task.priority or "Medium"
    return auto if order.get(auto, 99) < order.get(stored, 99) else stored


# ══════════════════════════════════════════════════════════════════════════════
#  DB HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_task_by_id(task_id: int, db: Session) -> Optional[Task]:
    return db.query(Task).filter(Task.id == task_id).first()


def update_task_priority(task_id: int, priority: str, db: Session) -> bool:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return False
    task.priority = priority
    db.commit()
    return True


def get_all_pending_tasks(db: Session) -> list:
    return (
        db.query(Task)
        .filter(Task.status.in_(["pending", "in_progress"]))
        .order_by(Task.id)
        .all()
    )


# ══════════════════════════════════════════════════════════════════════════════
#  DEADLINE PARSER
# ══════════════════════════════════════════════════════════════════════════════

def parse_deadline(message: str) -> Optional[date]:
    msg   = message.lower()
    today = datetime.now().date()

    if re.search(r"\b(today|tonight)\b", msg):  return today
    if re.search(r"\btomorrow\b", msg):          return today + timedelta(days=1)

    m = re.search(r"\bin\s+(\d+)\s+days?\b", msg)
    if m: return today + timedelta(days=int(m.group(1)))

    if re.search(r"\bnext\s+week\b", msg): return today + timedelta(days=7)

    m = re.search(r"\bend\s+of\s+(the\s+)?week\b", msg)
    if m:
        days_to_friday = (4 - today.weekday()) % 7
        return today + timedelta(days=days_to_friday or 7)

    days_map = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
    m = re.search(
        r"\b(by\s+|this\s+)(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", msg
    )
    if m:
        target_day = days_map[m.group(2)]
        delta      = (target_day - today.weekday()) % 7 or 7
        return today + timedelta(days=delta)

    m = re.search(r"\bby\s+(\d{1,2})[\/\-](\d{1,2})\b", msg)
    if m:
        try:
            month, day = int(m.group(1)), int(m.group(2))
            target = date(today.year, month, day)
            if target < today:
                target = date(today.year + 1, month, day)
            return target
        except ValueError:
            pass

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  DAILY PRIORITY REFRESH
# ══════════════════════════════════════════════════════════════════════════════

def daily_priority_refresh(db: Session) -> list:
    pending = db.query(Task).filter(
        Task.status.in_(["pending", "in_progress"]),
        Task.due_date.isnot(None),
    ).all()
    escalated = []
    for task in pending:
        new_priority = compute_auto_priority(task)
        if new_priority != task.priority:
            old = task.priority
            task.priority = new_priority
            escalated.append((task.id, task.title, old, new_priority))
    if escalated:
        db.commit()
    return escalated


# ══════════════════════════════════════════════════════════════════════════════
#  TASK EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def extract_task_from_message(message: str) -> tuple[dict, bool]:
    msg_lower = message.lower()

    priority_was_explicit = True
    explicit_priority     = None

    if any(w in msg_lower for w in ["critical", "urgent", "asap", "immediately"]):
        explicit_priority = "Critical"
    elif any(w in msg_lower for w in ["high priority", "high-priority", "important"]):
        explicit_priority = "High"
    elif re.search(r"\bhigh\b", msg_lower):
        explicit_priority = "High"
    elif any(w in msg_lower for w in ["low priority", "low-priority", "someday", "eventually", "later"]):
        explicit_priority = "Low"
    elif re.search(r"\blow\b", msg_lower):
        explicit_priority = "Low"
    elif any(w in msg_lower for w in ["medium priority", "medium", "middle", "normal priority"]):
        explicit_priority = "Medium"
    else:
        priority_was_explicit = False

    due_date      = parse_deadline(message)
    auto_priority = None
    if due_date:
        days_left = (due_date - date.today()).days
        if days_left <= 0:   auto_priority = "Critical"
        elif days_left <= 1: auto_priority = "Critical"
        elif days_left <= 3: auto_priority = "High"
        elif days_left <= 7: auto_priority = "Medium"
        else:                auto_priority = "Low"
        if auto_priority:
            priority_was_explicit = True

    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    if explicit_priority and auto_priority:
        final_priority = explicit_priority if order[explicit_priority] <= order[auto_priority] else auto_priority
    else:
        final_priority = explicit_priority or auto_priority or "Medium"

    category = "Work"
    cat_map  = {
        "Development": ["code","bug","fix","develop","api","database","deploy","test",
                        "refactor","frontend","backend","pr","commit","push"],
        "Learning":    ["learn","study","research","read","course","tutorial","docs","documentation"],
        "Personal":    ["personal","gym","health","family","grocery","groceries","home",
                        "parents","mom","dad","call","friend","doctor","dentist","chores",
                        "cook","clean","shopping","haircut","coffee","buy","walk","dog"],
        "Finance":     ["pay","bill","invoice","bank","transfer","budget","tax","expense",
                        "salary","finance","money"],
        "Work":        ["meeting","email","report","review","client","presentation",
                        "plan","project","boss","team"],
    }
    for cat, keywords in cat_map.items():
        if any(k in msg_lower for k in keywords):
            category = cat
            break

    est_minutes   = 60
    time_patterns = [
        (r"(\d+)\s*hour",  lambda m: int(m.group(1)) * 60),
        (r"(\d+)\s*hr",    lambda m: int(m.group(1)) * 60),
        (r"(\d+)\s*min",   lambda m: int(m.group(1))),
        (r"half an? hour", lambda _: 30),
        (r"quarter hour",  lambda _: 15),
        (r"2\s*hours?",    lambda _: 120),
    ]
    for pattern, extractor in time_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            try:
                est_minutes = extractor(match)
            except Exception:
                pass
            break

    title  = message
    filler = [
        r"^(add|create|make|new|schedule|set up)\s+(a\s+)?(new\s+)?task\s+(to\s+|for\s+)?",
        r"^(remind me to|i need to|i want to|i have to|don'?t forget to)\s+",
        r",?\s*\d+\s*(hour|hr|min|minute)s?(\s+long)?\s*$",
        r",?\s*(half an? hour|quarter hour)\s*$",
        r",?\s*(top\s+)?priority\s*[:\-]?\s*(critical|urgent|high|medium|middle|low|normal)\s*$",
        r",?\s*(critical|urgent|asap|high|medium|middle|normal|low)\s+priority\s*$",
        r",?\s*it'?s?\s*(critical|urgent|high|medium|low|important)\s*$",
        r",?\s*\b(critical|urgent|asap)\b\s*$",
        r",?\s*\b(high|important)\s*priority\b\s*$",
        r",?\s*\b(low|someday|eventually)\s*priority\b\s*$",
        r",?\s*\bpriority\s+(high|low|medium|critical)\b\s*$",
        r",?\s*\b(high|low|medium|critical)\b\s*$",
        r",?\s*category\s*[:\-]?\s*\w+\s*$",
        r",?\s*(due\s+)?(by\s+|this\s+)?(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*$",
        r",?\s*due\s+(by\s+)?\d{1,2}[\/\-]\d{1,2}\s*$",
        r",?\s*(in\s+\d+\s+days?|next\s+week|end\s+of\s+(the\s+)?week)\s*$",
        r",?\s*estimated?\s*(time\s*)?\d+.*$",
    ]
    for _ in range(5):
        prev = title
        for f in filler:
            title = re.sub(f, "", title, flags=re.IGNORECASE).strip()
        if title == prev:
            break

    title = re.sub(r"[,;\-]+$", "", title).strip()
    title = re.sub(r"\s+(and|with|at|in|on|for|to)$", "", title, flags=re.IGNORECASE).strip()
    if not title:
        title = "New Task"
    else:
        title = title[0].upper() + title[1:]

    return (
        {
            "title":             title,
            "priority":          final_priority,
            "category":          category,
            "estimated_minutes": est_minutes,
            "due_date":          datetime.combine(due_date, datetime.min.time()) if due_date else None,
            "status":            "pending",
            "notes":             "",
        },
        priority_was_explicit,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  SMART FOLLOW-UP
# ══════════════════════════════════════════════════════════════════════════════

def smart_follow_up(db: Session, last_action: str, task_id: int = None) -> str:
    pending  = db.query(Task).filter(Task.status.in_(["pending", "in_progress"])).count()
    critical = db.query(Task).filter(Task.priority == "Critical", Task.status != "completed").count()
    unset    = db.query(Task).filter(Task.priority == "Medium", Task.status != "completed").count()

    if last_action == "task_created":
        if critical > 2:
            return f"\n\n💡 You have {critical} critical tasks — say 'plan my day' to tackle them in order."
        if unset > 3:
            return f"\n\n💡 {unset} tasks have no priority — say 'review priorities' to sort them fast."
        return "\n\n💡 Say 'plan my day' to see your full schedule."

    if last_action == "task_completed":
        if critical > 0:
            return f"\n\n🔥 {critical} critical task(s) still pending — keep the momentum!"
        if pending == 0:
            return "\n\n🎉 You cleared everything! Say 'show my stats' to see your progress."
        return f"\n\n⏭️ {pending} tasks left — say 'plan my day' for what's next."

    if last_action == "priority_set":
        return "\n\n📅 Say 'plan my day' to see your updated schedule."

    return ""


# ══════════════════════════════════════════════════════════════════════════════
#  EXECUTE TASK ACTION
# ══════════════════════════════════════════════════════════════════════════════

def execute_task_action(intent: str, message: str, db: Session) -> Optional[dict]:
    if intent == "create_task":
        task_data, priority_was_explicit = extract_task_from_message(message)
        db_task = Task(**task_data)
        db.add(db_task)
        db.commit()
        db.refresh(db_task)
        return {
            "action":                "task_created",
            "task_id":               db_task.id,
            "task_title":            db_task.title,
            "priority":              db_task.priority,
            "category":              db_task.category,
            "estimated_minutes":     db_task.estimated_minutes,
            "due_date":              db_task.due_date.date().isoformat() if db_task.due_date else None,
            "priority_was_explicit": priority_was_explicit,
        }
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

def handle_greeting(db: Session) -> dict:
    hour = datetime.now().hour
    if hour < 12:
        time_greeting, energy_tip = "Good morning", "🧠 Morning = peak focus. Tackle your hardest task first."
    elif hour < 17:
        time_greeting, energy_tip = "Good afternoon", "☕ Start with a quick win to build momentum."
    else:
        time_greeting, energy_tip = "Good evening", "🌙 Great time to plan tomorrow or knock out low-effort tasks."

    pending   = db.query(Task).filter(Task.status.in_(["pending", "in_progress"])).all()
    critical  = [t for t in pending if t.priority in ("Critical", "Overdue")]
    high      = [t for t in pending if t.priority == "High"]
    total_min = sum(t.estimated_minutes or 60 for t in pending[:8])
    hrs, mins = total_min // 60, total_min % 60

    if not pending:
        return {
            "reply": (
                f"{time_greeting}! 👋\n\n"
                f"🎉 Your task list is empty — you're all caught up!\n\n"
                f"{energy_tip}\n\nSay 'add a task to...' whenever you're ready."
            ),
            "intent": "general_chat", "action_taken": None, "session_update": {},
        }

    lines = [f"{time_greeting}! 👋 Here's your snapshot:\n"]
    lines.append(f"📋 {len(pending)} tasks pending · ~{hrs}h {mins}min of work\n")

    if critical:
        lines.append(f"🔴 {len(critical)} Critical/Overdue — needs attention today:")
        for t in critical[:3]:
            due_str = f" (due {t.due_date.date()})" if t.due_date else ""
            lines.append(f"   → #{t.id} {t.title}{due_str}")
        lines.append("")

    if high:
        lines.append(f"🟠 {len(high)} High priority tasks queued\n")

    lines.append(energy_tip)
    lines.append("\nWhat would you like to do?")
    lines.append("📅 'plan my day' · ➕ 'add a task' · ✅ 'complete task #X' · 📊 'show my stats'")

    # ── Phase A: Personalized insights ──────────────────────────────────────
    # Use cached patterns (fast, no DB hit)
    patterns = get_cached_patterns()
    insights = get_personalized_insights(patterns)
    if insights:
        lines.append("\n🧠 Your patterns:")
        lines.extend(f"  {i}" for i in insights[:3])  # max 3 in greeting

    return {
        "reply": "\n".join(lines),
        "intent": "general_chat", "action_taken": None, "session_update": {},
    }


def handle_help() -> dict:
    return {
        "reply": (
            "🧠 Here's what I can do!\n\n"
            "➕ Add a Task\n"
            "  'add a task to fix the login bug'\n"
            "  'add a task to call dentist, high priority, 30 minutes'\n"
            "  'remind me to submit report by Friday' ← deadline auto-sets priority!\n\n"
            "📋 View Tasks\n"
            "  'show my tasks'\n"
            "  'show high priority tasks' · 'show critical tasks'\n\n"
            "✅ Complete a Task\n"
            "  'complete task #3' · 'mark task 5 as done'\n\n"
            "🎯 Update Priority\n"
            "  'set task #3 priority to high'\n"
            "  'set tasks #3 high, #4 low, #5 critical' ← bulk update\n"
            "  'review priorities' ← guided wizard\n\n"
            "📅 Plan Your Day\n"
            "  'plan my day' · 'what should I work on today?'\n\n"
            "📊 Stats & Insights\n"
            "  'show my stats' · 'how productive have I been?'\n"
            "  'what have I been procrastinating on?'\n"
            "  'am I on track for my daily goal?'\n"
            "  'what category do I spend most time on?'\n\n"
            "Just talk naturally — typos are fine! 😊"
        ),
        "intent": "help", "action_taken": None, "session_update": {},
    }


def handle_list_tasks(message: str, db: Session) -> dict:
    msg_lower = message.lower()
    query     = db.query(Task)

    if "completed" in msg_lower or "done" in msg_lower:
        tasks  = query.filter(
            Task.status.in_(["completed", "archived"])
        ).order_by(Task.completed_at.desc()).limit(15).all()
        header = "✅ Completed Tasks"
    elif "critical" in msg_lower or "overdue" in msg_lower:
        tasks  = query.filter(Task.priority.in_(["Critical","Overdue"]), Task.status.in_(["pending","in_progress"])).all()
        header = "🔴 Critical / Overdue Tasks"
    elif "high" in msg_lower:
        tasks  = query.filter(Task.priority == "High", Task.status.in_(["pending","in_progress"])).all()
        header = "🟠 High Priority Tasks"
    elif "low" in msg_lower:
        tasks  = query.filter(Task.priority == "Low", Task.status.in_(["pending","in_progress"])).all()
        header = "🟢 Low Priority Tasks"
    else:
        tasks  = query.filter(Task.status.in_(["pending","in_progress"])).all()
        header = "📋 Pending Tasks"

    if not tasks:
        return {
            "reply": "🎉 No tasks found! Try 'add a task to...' to create one.",
            "intent": "list_tasks", "action_taken": None, "session_update": {},
        }

    order        = {"Overdue":0,"Critical":1,"High":2,"Medium":3,"Low":4}
    tasks_sorted = sorted(tasks, key=lambda t: order.get(resolve_priority(t), 99))
    today        = date.today()
    lines        = [f"{header} — {len(tasks_sorted)} total\n"]
    unset_count  = 0

    for t in tasks_sorted:
        display_priority = resolve_priority(t)
        p_icon  = PRIORITY_EMOJI.get(display_priority, "⚪")
        s_icon  = STATUS_EMOJI.get(t.status, "❓")
        dur     = f" · ⏱️ {t.estimated_minutes}min" if t.estimated_minutes else ""
        due_str = ""
        if t.due_date:
            d         = t.due_date.date()
            days_left = (d - today).days
            if days_left < 0:    due_str = f" · 📅 OVERDUE ({d})"
            elif days_left == 0: due_str = f" · 📅 Due today!"
            elif days_left == 1: due_str = f" · 📅 Due tomorrow"
            else:                due_str = f" · 📅 {d}"

        is_unset = (t.priority == "Medium" and not t.due_date)
        flag     = " (no priority set)" if is_unset else ""
        if is_unset:
            unset_count += 1

        lines.append(f"{p_icon} #{t.id} {t.title}{flag} {s_icon}{dur}{due_str}")

    lines.append("\n💡 Say 'complete task #X' to mark done · 'add a task to...' to create one.")

    if unset_count >= 3:
        lines.append(
            f"\n─────────────────────────────\n"
            f"💡 {unset_count} tasks have no priority set.\n"
            f"Say 'review priorities' and I'll walk you through them one by one!"
        )

    return {
        "reply": "\n".join(lines),
        "intent": "list_tasks", "action_taken": None, "session_update": {},
    }


def handle_create_task(message: str, db: Session) -> dict:
    action_taken = execute_task_action("create_task", message, db)
    if not action_taken:
        return {
            "reply": "⚠️ Couldn't parse a task. Try: 'add a task to fix the login bug'",
            "intent": "create_task", "action_taken": None, "session_update": {},
        }

    t                     = action_taken
    p_icon                = PRIORITY_EMOJI.get(t["priority"], "")
    priority_was_explicit = t.get("priority_was_explicit", True)
    dur_str               = f"\n• Estimated: {t['estimated_minutes']} min" if t["estimated_minutes"] else ""
    due_str               = f"\n• Due: {t['due_date']}" if t.get("due_date") else ""

    priority_hint = ""
    if not priority_was_explicit:
        priority_hint = (
            f"\n\n─────────────────────────────\n"
            f"Does that priority feel right?\n"
            f"🔴 Critical — must happen today\n"
            f"🟠 High     — important this week\n"
            f"🟡 Medium   — flexible, no real deadline ← current\n"
            f"🟢 Low      — whenever you get to it\n\n"
            f"Say 'set task #{t['task_id']} priority to high' to update!"
        )

    follow_up = smart_follow_up(db, "task_created", t["task_id"])

    return {
        "reply": (
            f"✅ Task created!\n\n"
            f"#{t['task_id']} {t['task_title']}\n"
            f"• Priority: {p_icon} {t['priority']}"
            + ("" if priority_was_explicit else " (default — no priority mentioned)")
            + f"\n• Category: {t['category']}"
            + dur_str + due_str + priority_hint + follow_up
        ),
        "intent": "create_task", "action_taken": action_taken, "session_update": {},
    }


def handle_complete_task(message: str, db: Session) -> dict:
    patterns = [
        r'task\s*#?(\d+)',
        r'#(\d+)',
        r'(?:complete|done|finish|mark)\s+(\d+)',
        r'(\d+)\s+(?:done|complete|finished)',
    ]
    task_id = None
    for pat in patterns:
        m = re.search(pat, message.lower())
        if m:
            task_id = int(m.group(1))
            break

    if not task_id:
        return {
            "reply": (
                "Please include the task number, e.g.:\n"
                "'complete task #3' or 'mark task 5 as done'\n\n"
                "Not sure of the ID? Say 'show my tasks' first."
            ),
            "intent": "complete_task", "action_taken": None, "session_update": {},
        }

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return {
            "reply": f"⚠️ Couldn't find task #{task_id}. Say 'show my tasks' to see all IDs.",
            "intent": "complete_task", "action_taken": None, "session_update": {},
        }

    if task.status == "completed":
        return {
            "reply": f"✅ Task #{task_id} — {task.title} is already completed!",
            "intent": "complete_task", "action_taken": None, "session_update": {},
        }

    task.status       = "completed"
    task.completed_at = datetime.utcnow()

    if task.created_at:
        elapsed      = datetime.utcnow() - task.created_at
        elapsed_mins = int(elapsed.total_seconds() / 60)
        task.actual_minutes = min(elapsed_mins, 480)

    db.commit()

    try:
        analyze_user_patterns(db, user_id=0)
    except Exception as e:
        logger.warning(f"[Patterns] Post-completion recalculation failed: {e}")
    predictor.retrain_if_ready(db)

    follow_up = smart_follow_up(db, "task_completed", task.id)

    ml_note = ""
    if predictor.is_trained and task.estimated_minutes and task.actual_minutes:
        diff = task.actual_minutes - task.estimated_minutes
        if abs(diff) > 10:
            direction = "longer" if diff > 0 else "shorter"
            ml_note   = f"\n🤖 Took {abs(diff)}min {direction} than estimated — ML model updated."

    return {
        "reply": (
            f"🎉 Done! Task marked as complete:\n\n"
            f"#{task.id} {task.title}\n"
            f"• Priority was: {PRIORITY_EMOJI.get(task.priority, '')} {task.priority}\n"
            f"• Completed at: {datetime.now().strftime('%H:%M')}"
            + ml_note + follow_up
        ),
        "intent": "complete_task",
        "action_taken": {"action": "task_completed", "task_id": task.id, "task_title": task.title},
        "session_update": {},
    }


def handle_set_priority(message: str, db: Session) -> dict:
    id_match  = re.search(r"#?(\d+)", message)
    pri_match = re.search(r"\b(critical|high|medium|low)\b", message, re.IGNORECASE)

    if not id_match or not pri_match:
        return {
            "reply": (
                "Please specify both the task number and priority, e.g.:\n"
                "'set task #3 priority to high'\n\n"
                "Priorities: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low"
            ),
            "intent": "set_priority", "action_taken": None, "session_update": {},
        }

    task_id  = int(id_match.group(1))
    priority = pri_match.group(1).capitalize()
    task     = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        return {
            "reply": f"⚠️ Task #{task_id} not found. Say 'show my tasks' to see all IDs.",
            "intent": "set_priority", "action_taken": None, "session_update": {},
        }

    task.priority = priority
    db.commit()

    follow_up = smart_follow_up(db, "priority_set")
    return {
        "reply": (
            f"✅ Updated!\n\n"
            f"#{task.id} {task.title}\n"
            f"• Priority → {PRIORITY_EMOJI.get(priority, '')} {priority}"
            + follow_up
        ),
        "intent": "set_priority",
        "action_taken": {"action": "priority_updated", "task_id": task.id, "priority": priority},
        "session_update": {},
    }


def handle_bulk_set_priority(message: str, db: Session) -> dict:
    pri_map = {"critical":"Critical","high":"High","medium":"Medium","low":"Low"}
    pairs   = re.findall(r"#?(\d+)\s+(critical|high|medium|low)", message, re.IGNORECASE)

    if not pairs:
        return {
            "reply": "Couldn't parse that. Try:\n'set tasks #3 high, #4 low, #5 critical'",
            "intent": "bulk_set_priority", "action_taken": None, "session_update": {},
        }

    lines   = ["✅ Updated priorities:\n"]
    updated = []
    for task_id_str, pri_str in pairs:
        task_id  = int(task_id_str)
        priority = pri_map[pri_str.lower()]
        ok       = update_task_priority(task_id, priority, db)
        if ok:
            task = get_task_by_id(task_id, db)
            lines.append(f"{PRIORITY_EMOJI.get(priority,'')} #{task_id} {task.title} → {priority}")
            updated.append(task_id)
        else:
            lines.append(f"⚠️ #{task_id} not found — skipped")

    lines.append(smart_follow_up(db, "priority_set"))
    return {
        "reply": "\n".join(lines),
        "intent": "bulk_set_priority",
        "action_taken": {"action": "bulk_priority_updated", "task_ids": updated},
        "session_update": {},
    }


def handle_start_priority_wizard(db: Session) -> dict:
    all_pending = get_all_pending_tasks(db)
    if not all_pending:
        return {
            "reply": "🎉 No pending tasks to review! Say 'add a task' to get started.",
            "intent": "review_priorities", "action_taken": None, "session_update": {},
        }

    queue   = [t.id for t in all_pending]
    first   = all_pending[0]
    dur_str = f" ⏱️ {first.estimated_minutes}min" if first.estimated_minutes else ""
    p_icon  = PRIORITY_EMOJI.get(first.priority, "⚪")
    due_str = f" · 📅 due {first.due_date.date()}" if first.due_date else ""

    return {
        "reply": (
            f"🎯 Review Priorities 🧭 Priority Wizard\n"
            f"Let's review all {len(queue)} pending tasks and make sure priorities are right.\n"
            f"Reply with one letter — S keeps the current priority.\n\n"
            f"🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⏭️ Skip\n\n"
            f"───────────────────────\n"
            f"{p_icon} #{first.id} {first.title}{dur_str}{due_str}\n"
            f"Current: {first.priority} · Change to? [C / H / M / L / S]"
        ),
        "intent": "review_priorities",
        "action_taken": None,
        "session_update": {
            "priority_review_active": True,
            "priority_review_queue":  queue,
        },
    }


def handle_priority_wizard_step(message: str, db: Session, session_state: dict) -> dict:
    queue   = list(session_state.get("priority_review_queue", []))
    mapping = {"c": "Critical", "h": "High", "m": "Medium", "l": "Low"}
    key     = message.strip().lower()[0] if message.strip() else ""

    if not queue:
        return {
            "reply": "🎉 All done! Say 'show my tasks' to see your updated list.",
            "intent": "priority_review_done", "action_taken": None,
            "session_update": {"priority_review_active": False, "priority_review_queue": []},
        }

    current_task_id = queue[0]

    if message.strip().lower() in ("stop", "exit", "cancel", "quit"):
        return {
            "reply": "✅ Priority review stopped. Say 'show my tasks' to see where things stand.",
            "intent": "priority_review_done", "action_taken": None,
            "session_update": {"priority_review_active": False, "priority_review_queue": []},
        }

    if key == "s":
        queue.pop(0)
    elif key in mapping:
        update_task_priority(current_task_id, mapping[key], db)
        queue.pop(0)
    else:
        task    = get_task_by_id(current_task_id, db)
        p_icon  = PRIORITY_EMOJI.get(task.priority, "⚪") if task else "⚪"
        dur_str = f" ⏱️ {task.estimated_minutes}min" if task and task.estimated_minutes else ""
        due_str = f" · 📅 due {task.due_date.date()}" if task and task.due_date else ""
        return {
            "reply": (
                f"❓ Please reply with just one letter:\n"
                f"🔴 C · 🟠 H · 🟡 M · 🟢 L · ⏭️ S (keep as-is)\n\n"
                f"{p_icon} #{task.id} {task.title}{dur_str}{due_str}\n"
                f"Current: {task.priority}"
            ),
            "intent": "priority_review_step", "action_taken": None,
            "session_update": {"priority_review_active": True, "priority_review_queue": queue},
        }

    if queue:
        next_task = get_task_by_id(queue[0], db)
        p_icon    = PRIORITY_EMOJI.get(next_task.priority, "⚪") if next_task else "⚪"
        dur_str   = f" ⏱️ {next_task.estimated_minutes}min" if next_task and next_task.estimated_minutes else ""
        due_str   = f" · 📅 due {next_task.due_date.date()}" if next_task and next_task.due_date else ""
        return {
            "reply": (
                f"🧭 Priority Wizard\n"
                f"{len(queue)} left · ───────────────────────\n"
                f"{p_icon} #{next_task.id} {next_task.title}{dur_str}{due_str}\n"
                f"Current: {next_task.priority} · Change to? [C / H / M / L / S]"
            ),
            "intent": "priority_review_step", "action_taken": None,
            "session_update": {"priority_review_active": True, "priority_review_queue": queue},
        }
    else:
        return {
            "reply": "🎉 All priorities reviewed!\n\nSay 'plan my day' to get your optimized schedule.",
            "intent": "priority_review_done", "action_taken": None,
            "session_update": {"priority_review_active": False, "priority_review_queue": []},
        }


def handle_analytics(db: Session) -> dict:
    from collections import Counter

    total    = db.query(Task).count()
    done     = db.query(Task).filter(Task.status == "completed").count()
    pending  = db.query(Task).filter(Task.status.in_(["pending","in_progress"])).count()
    rate     = round(done / total * 100, 1) if total > 0 else 0
    critical = db.query(Task).filter(Task.priority.in_(["Critical","Overdue"]), Task.status != "completed").count()
    high     = db.query(Task).filter(Task.priority == "High", Task.status != "completed").count()

    completed_tasks = db.query(Task).filter(Task.status == "completed").all()
    cat_counts      = Counter(t.category for t in completed_tasks)
    cat_lines       = []
    for cat, count in cat_counts.most_common(5):
        bar = "█" * min(count, 10)
        cat_lines.append(f"   {bar} {cat}: {count} done")

    if rate >= 80:   mood = "🔥 You're on fire! Incredible consistency."
    elif rate >= 60: mood = "💪 Solid progress — keep the momentum going!"
    elif rate >= 40: mood = "📈 Making progress. Push through the backlog!"
    elif rate >= 20: mood = "🌱 Early days — every completed task counts."
    else:            mood = "💡 Just get one task done today — that's all it takes."

    total_actual   = sum(t.actual_minutes or 0 for t in completed_tasks)
    hours_invested = total_actual // 60

    streak_data = get_streak(db, user_id=0)
    streak_cur  = streak_data["current"]
    streak_long = streak_data["longest"]
    today_count = streak_data["today_count"]

    lines = [
        "📊 Your Productivity Stats\n",
        f"• Total tasks logged: {total}",
        f"• ✅ Completed: {done} ({rate}%)",
        f"• ⏳ Still pending: {pending}",
        f"• 🔴 Critical/Overdue right now: {critical}",
        f"• 🟠 High priority remaining: {high}",
        f"• 📅 Completed today: {today_count}",
    ]

    if hours_invested > 0:
        lines.append(f"• ⏱️ Total time invested: ~{hours_invested}h")

    if streak_cur >= 7:
        lines.append(f"• 🔥 {streak_cur}-day streak! You're unstoppable.")
    elif streak_cur >= 3:
        lines.append(f"• ⚡ {streak_cur}-day streak — keep it alive!")
    elif streak_cur == 1:
        lines.append(f"• ✅ Streak started! Come back tomorrow to keep it going.")

    if streak_long > streak_cur and streak_long >= 3:
        lines.append(f"• 🏆 Longest streak ever: {streak_long} days")

    if cat_lines:
        lines.append("\n📁 Completed by category:")
        lines.extend(cat_lines)

    if predictor.is_trained:
        estimable = [t for t in completed_tasks if t.actual_minutes and t.estimated_minutes]
        if estimable:
            mae = sum(abs(t.actual_minutes - t.estimated_minutes) for t in estimable) / len(estimable)
            lines.append(f"\n🤖 ML Predictor: ✅ Active — avg accuracy: ±{mae:.0f}min")
        else:
            lines.append("\n🤖 ML Predictor: ✅ Active — predictions improving with each task")
    else:
        remaining = max(0, 5 - done)
        lines.append(f"\n🤖 ML Predictor: ⚠️ Not yet trained — complete {remaining} more task(s) to enable ML estimates")

    lines.append(f"\n{mood}")

    return {
        "reply": "\n".join(lines),
        "intent": "task_analytics", "action_taken": None, "session_update": {},
    }


def handle_get_plan(db: Session) -> dict:
    pending = db.query(Task).filter(Task.status.in_(["pending","in_progress"])).all()

    if not pending:
        return {
            "reply": "🎉 No pending tasks!\n\nYou're completely caught up.",
            "intent": "get_plan", "action_taken": None, "session_update": {},
        }

    today    = date.today()
    pri_ord  = {"Overdue":0,"Critical":1,"High":2,"Medium":3,"Low":4}

    # ── Phase A: Apply personalized ordering ────────────────────────────────
    patterns = get_cached_patterns()
    pending  = adjust_plan_for_user(pending, patterns)
    # ────────────────────────────────────────────────────────────────────────

    # ── Show personalization note if active ─────────────────────────────────
    peak_hour = patterns.get("peak_hour")
    now_hour  = datetime.now().hour
    is_peak   = peak_hour and abs(now_hour - peak_hour) <= 1

    sorted_tasks = sorted(
        pending,
        key=lambda t: (pri_ord.get(resolve_priority(t), 99), t.due_date or datetime.max),
    )

    overdue   = [t for t in sorted_tasks if t.due_date and t.due_date.date() < today]
    due_today = [t for t in sorted_tasks if t.due_date and t.due_date.date() == today]
    rest      = [t for t in sorted_tasks if t not in overdue and t not in due_today]

    hour       = datetime.now().hour
    start_hour = max(hour, 8)

    def fmt_time(offset_mins: int) -> str:
        total = start_hour * 60 + offset_mins
        h, m  = divmod(total, 60)
        return f"{h % 24:02d}:{m:02d}"

    # Use adjusted estimate if available (from adjust_plan_for_user)
    def get_est(t):
        return getattr(t, "_adjusted_estimate", t.estimated_minutes or 60)

    lines  = ["📅 Your Plan for Today\n"]

    # Show personalization note
    if patterns.get("has_enough_data"):
        if is_peak:
            lines.append(f"⚡ Peak focus hour ({peak_hour}:00) — hardest tasks first!\n")
        elif peak_hour:
            h_display = peak_hour if peak_hour <= 12 else peak_hour - 12
            suffix    = "AM" if peak_hour < 12 else "PM"
            lines.append(f"💡 Your peak hour is {h_display}{suffix} — quick tasks now, hard ones then.\n")

    offset = 0

    def add_line(t):
        nonlocal offset
        dur      = get_est(t)
        p_icon   = PRIORITY_EMOJI.get(resolve_priority(t), "⚪")
        slot     = fmt_time(offset)
        end_slot = fmt_time(offset + dur)
        cat      = f" [{t.category}]" if t.category else ""
        ov_flag  = " ⚠️ overdue" if t.due_date and t.due_date.date() < today else ""
        lines.append(f"{p_icon} {slot}–{end_slot} #{t.id} {t.title}{cat}{ov_flag}")
        offset  += dur + 10

    if overdue:
        lines.append("🚨 Overdue — Do First:")
        for t in overdue: add_line(t)
        lines.append("")

    if due_today:
        lines.append("🎯 Due Today:")
        for t in due_today: add_line(t)
        lines.append("")

    top_rest = rest[:6]
    if top_rest:
        lines.append("📋 Up Next:")
        for t in top_rest: add_line(t)
        if len(rest) > 6:
            lines.append(f"   ...and {len(rest) - 6} more tasks not shown")
        lines.append("")

    shown_min = sum(get_est(t) for t in overdue + due_today + top_rest)
    total_min = sum(get_est(t) for t in sorted_tasks)
    h, m      = divmod(shown_min, 60)
    lines.append(f"⏱️ Shown: ~{h}h {m}min")

    if total_min > 480:
        lines.append(f"⚠️ Full backlog = ~{total_min // 60}h. Focus Critical/High first.")

    unset = [t for t in sorted_tasks if t.priority == "Medium" and not t.due_date]
    if unset:
        lines.append(f"\n💡 {len(unset)} tasks have no priority set — say 'review priorities'.")

    return {
        "reply": "\n".join(lines),
        "intent": "get_plan", "action_taken": None, "session_update": {},
    }

def handle_procrastination(db: Session) -> dict:
    pending = db.query(Task).filter(Task.status.in_(["pending","in_progress"])).all()
    if not pending:
        return {
            "reply": "🎉 Nothing to procrastinate on — you're all caught up!",
            "intent": "procrastination", "action_taken": None, "session_update": {},
        }

    def age_key(t):
        raw = t.created_at
        return raw if raw else datetime.now()

    sorted_old = sorted(pending, key=age_key)
    today      = date.today()
    lines      = ["😬 Tasks You've Been Avoiding:\n"]

    for t in sorted_old[:5]:
        try:
            created  = t.created_at.date() if t.created_at else today
            days_old = (today - created).days
            age_tag  = f"waiting {days_old}d" if days_old > 0 else "added today"
        except Exception:
            age_tag = "unknown age"
        emoji = PRIORITY_EMOJI.get(t.priority, "🟡")
        lines.append(f"{emoji} #{t.id} {t.title} — {age_tag}")

    lines.append(
        "\n💡 Pick the smallest one and say 'complete task X' after you're done. "
        "Even 10 minutes of progress beats zero!"
    )
    return {
        "reply": "\n".join(lines),
        "intent": "procrastination", "action_taken": None, "session_update": {},
    }


def handle_goal_check(db: Session) -> dict:
    from app.ml.streaks import get_streak
    streak_data = get_streak(db, user_id=0)
    today_count = streak_data["today_count"]

    # ✅ Read daily_goal from profile file (same logic as calendar)
    try:
        import json
        from pathlib import Path
        pfile = Path(__file__).parent.parent.parent / "user_profile.json"
        daily_goal = json.load(open(pfile)).get("daily_goal", 5) if pfile.exists() else 5
    except Exception:
        daily_goal = 5

    remaining = max(0, daily_goal - today_count)

    if today_count >= daily_goal:
        return {
            "reply": (
                f"🏆 Goal Crushed!\n\n"
                f"You've completed {today_count}/{daily_goal} tasks today"
                + (f" — that's {today_count - daily_goal} extra! 🎉" if today_count > daily_goal else "! 🎉")
                + "\n\nSay 'plan my day' to keep the momentum going!"
            ),
            "intent": "goal_check", "action_taken": None, "session_update": {},
        }
    elif today_count == 0:
        return {
            "reply": (
                f"🎯 Daily Goal: 0/{daily_goal} tasks completed\n\n"
                f"Not started yet — you need {remaining} task(s) to hit your goal today.\n\n"
                f"💡 Say 'plan my day' to find a quick first win!"
            ),
            "intent": "goal_check", "action_taken": None, "session_update": {},
        }
    else:
        pct = round(today_count / daily_goal * 100)
        return {
            "reply": (
                f"📊 Daily Goal: {today_count}/{daily_goal} ({pct}%)\n\n"
                f"You need {remaining} more task(s) to hit your goal today.\n\n"
                + ("💪 Almost there! Keep going!" if pct >= 60 else "🚀 Good start — keep the momentum!")
                + "\n\nSay 'plan my day' to see what's left!"
            ),
            "intent": "goal_check", "action_taken": None, "session_update": {},
        }


def handle_category_breakdown(db: Session) -> dict:
    completed = db.query(Task).filter(Task.status == "completed").all()
    pending   = db.query(Task).filter(Task.status.in_(["pending","in_progress"])).all()

    if not completed:
        return {
            "reply": (
                "📁 No completed tasks to analyze yet.\n\n"
                "Complete some tasks and I'll show you where your time is going!"
            ),
            "intent": "category_breakdown", "action_taken": None, "session_update": {},
        }

    cat_time:  dict[str, int] = {}
    cat_count: dict[str, int] = {}
    for t in completed:
        cat = t.category or "Uncategorized"
        mins = t.actual_minutes or t.estimated_minutes or 0
        cat_time[cat]  = cat_time.get(cat, 0) + mins
        cat_count[cat] = cat_count.get(cat, 0) + 1

    pend_time: dict[str, int] = {}
    for t in pending:
        cat = t.category or "Uncategorized"
        pend_time[cat] = pend_time.get(cat, 0) + (t.estimated_minutes or 0)

    max_time = max(cat_time.values()) if cat_time else 1
    lines    = ["📁 Time by Category\n"]

    for cat, mins in sorted(cat_time.items(), key=lambda x: -x[1]):
        bar      = "█" * max(1, round(mins / max_time * 5))
        hours    = round(mins / 60, 1)
        pend_h   = round(pend_time.get(cat, 0) / 60, 1)
        pend_tag = f" · {pend_h}h pending" if pend_h else ""
        lines.append(f"{bar} {cat} — {hours}h done{pend_tag} ({cat_count[cat]} tasks)")

    top_cat = max(cat_time, key=cat_time.get)
    lines.append(f"\n🏆 You invest most time in {top_cat}.")
    lines.append("💡 Say 'show my stats' for the full productivity breakdown.")

    return {
        "reply": "\n".join(lines),
        "intent": "category_breakdown", "action_taken": None, "session_update": {},
    }


# ══════════════════════════════════════════════════════════════════════════════
#  DELETE & ARCHIVE
# ══════════════════════════════════════════════════════════════════════════════

def handle_delete_task(message: str, db: Session) -> dict:
    id_match = re.search(r"#?(\d+)", message)
    if not id_match:
        return {
            "reply": "Which task should I delete? Say:\ndelete task #3\n\nNot sure of the ID? Say 'show my tasks' first.",
            "intent": "delete_task", "action_taken": None, "session_update": {},
        }

    task_id = int(id_match.group(1))
    task    = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        return {
            "reply": f"Task #{task_id} not found. Say 'show my tasks' to see all IDs.",
            "intent": "delete_task", "action_taken": None, "session_update": {},
        }

    title = task.title
    db.delete(task)
    db.commit()

    return {
        "reply": f"🗑️ Task #{task_id} '{title}' deleted.\n\nSay 'show my tasks' to see your updated list.",
        "intent": "delete_task",
        "action_taken": {"action": "task_deleted", "task_id": task_id, "task_title": title},
        "session_update": {},
    }


def auto_archive_completed(db: Session) -> int:
    """
    Only archive if your Task model actually supports 'archived' status.
    Disabled by default — uncomment when you add 'archived' to the status enum.
    """
    cutoff = datetime.utcnow() - timedelta(hours=24)
    old_completed = db.query(Task).filter(
        Task.status == "completed",
        Task.completed_at < cutoff,
    ).all()
    for task in old_completed:
        task.status = "archived"
    if old_completed:
        db.commit()
    return len(old_completed)
    # return 0


# ══════════════════════════════════════════════════════════════════════════════
#  CONTEXT BUILDER & SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

def build_task_context(db: Session) -> str:
    try:
        total    = db.query(Task).count()
        done     = db.query(Task).filter(Task.status == "completed").count()
        pending  = db.query(Task).filter(Task.status.in_(["pending","in_progress"])).count()
        critical = db.query(Task).filter(
            Task.priority.in_(["Critical","Overdue"]), Task.status != "completed"
        ).count()
        return f"User has {total} tasks: {done} completed, {pending} pending, {critical} critical/overdue."
    except Exception as e:
        logger.warning(f"Context build failed: {e}")
        return ""


SYSTEM_PROMPT = (
    "You are Cognitive — a warm, smart AI productivity coach. "
    "Keep replies concise and encouraging. Never robotic. "
    "If the user seems stressed or overwhelmed, acknowledge it briefly before helping. "
    "Use emojis sparingly. Never say 'As an AI...'."
)

GREETINGS = frozenset([
    "hi", "hello", "hey", "good morning", "good afternoon",
    "good evening", "sup", "yo", "morning", "howdy", "hiya",
])

def handle_predict(message: str, db: Session) -> dict:
    """
    Predict how long a task will take using the ML predictor.
    Triggered by: 'how long will X take', 'estimate task #3', etc.
    """
    # Try to find a task ID reference first
    id_match = re.search(r"#?(\d+)", message)

    if id_match:
        task_id = int(id_match.group(1))
        task    = db.query(Task).filter(Task.id == task_id).first()

        if not task:
            return {
                "reply": f"⚠️ Task #{task_id} not found. Say 'show my tasks' to see all IDs.",
                "intent": "task_predict", "action_taken": None, "session_update": {},
            }

        if not predictor.is_trained:
            done = db.query(Task).filter(Task.status == "completed").count()
            remaining = max(0, 5 - done)
            return {
                "reply": (
                    f"🤖 ML predictor not trained yet.\n\n"
                    f"Complete {remaining} more task(s) to enable time predictions.\n\n"
                    f"For now: #{task.id} {task.title} has a manual estimate of "
                    f"{task.estimated_minutes or 60} min."
                ),
                "intent": "task_predict", "action_taken": None, "session_update": {},
            }

        try:
            predicted = predictor.predict_single(task)
            est       = task.estimated_minutes or 60
            diff      = predicted - est
            sign      = "+" if diff > 0 else ""
            direction = "longer" if diff > 0 else "shorter"

            return {
                "reply": (
                    f"🤖 Time Prediction: #{task.id} {task.title}\n\n"
                    f"• Your estimate:   {est} min\n"
                    f"• ML prediction:   {predicted} min\n"
                    f"• Difference:      {sign}{diff} min ({direction} than you think)\n\n"
                    f"💡 Based on your past {db.query(Task).filter(Task.status == 'completed').count()} completed tasks."
                ),
                "intent": "task_predict", "action_taken": None, "session_update": {},
            }
        except Exception as e:
            logger.warning(f"[Predict] Error: {e}")
            return {
                "reply": (
                    f"⚠️ Prediction failed for task #{task_id}.\n"
                    f"Manual estimate: {task.estimated_minutes or 60} min."
                ),
                "intent": "task_predict", "action_taken": None, "session_update": {},
            }

    # No task ID — general estimate from message text
    if not predictor.is_trained:
        done      = db.query(Task).filter(Task.status == "completed").count()
        remaining = max(0, 5 - done)
        return {
            "reply": (
                f"🤖 ML predictor needs {remaining} more completed task(s) to activate.\n\n"
                f"Try: 'how long will task #3 take?' once you have a task ID."
            ),
            "intent": "task_predict", "action_taken": None, "session_update": {},
        }

    # Try to extract a description from the message
    task_data, _ = extract_task_from_message(message)
    temp_task    = Task(**{k: v for k, v in task_data.items() if k != "due_date"})

    try:
        predicted = predictor.predict_single(temp_task)
        return {
            "reply": (
                f"🤖 Estimated time for '{task_data['title']}':\n\n"
                f"• ML prediction: ~{predicted} min\n"
                f"• Category: {task_data['category']}\n"
                f"• Priority: {task_data['priority']}\n\n"
                f"💡 Say 'add a task to {task_data['title']}' to create it with this estimate."
            ),
            "intent": "task_predict", "action_taken": None, "session_update": {},
        }
    except Exception as e:
        logger.warning(f"[Predict] General prediction error: {e}")
        return {
            "reply": (
                "🤖 I can predict time for specific tasks.\n\n"
                "Try: 'how long will task #3 take?' or 'estimate task #5'"
            ),
            "intent": "task_predict", "action_taken": None, "session_update": {},
        }

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN SMART CHAT
# ══════════════════════════════════════════════════════════════════════════════

def smart_chat(
    message: str,
    user_id: int,
    db: Session,
    session_state: dict,
    conversation_history: list | None = None,
) -> dict:

    # FIX: _clean defined ONCE at the top of smart_chat (not twice)
    def _clean(result: dict) -> dict:
        if "reply" in result:
            result["reply"] = strip_markdown(result["reply"])
        return result

    if conversation_history is None:
        conversation_history = []

    msg_stripped = message.strip()
    msg_lower    = msg_stripped.lower()

    # 1. Wizard intercepts ALL input while active
    if session_state.get("priority_review_active"):
        return handle_priority_wizard_step(msg_stripped, db, session_state)

    # 2. Explicit data-analyst command
    if DATA_QUESTION_RE.match(msg_stripped):
        return _clean(handle_data_question(DATA_QUESTION_RE.sub("", msg_stripped, count=1), db))

    # 3. LLM tool-calling agent. Returns None if Ollama is down or the model
    #    can't call tools, in which case the rule-based routing below runs.
    from app.llm.agentic_chain import agentic_chat
    agent_result = agentic_chat(msg_stripped, db, conversation_history)
    if agent_result is not None:
        return agent_result

    # ── Rule-based fallback ────────────────────────────────────────────────
    if any(msg_lower == g or msg_lower.startswith(g + " ") for g in GREETINGS):
        return _clean(handle_greeting(db))

    if AUDIT_RE.search(msg_lower):
        return _clean(handle_cognitive_audit(db))

    # 4. Intent detection (ML → regex → fuzzy — all in detect_intent now)
    intent = detect_intent(msg_lower)
    logger.info(f"[SMART CHAT] intent: {intent} | msg: {msg_stripped[:60]}")

    # 4. Route
    if intent == "help":               return _clean(handle_help())
    if intent == "list_tasks":         return _clean(handle_list_tasks(msg_stripped, db))
    if intent == "create_task":        return _clean(handle_create_task(msg_stripped, db))
    if intent == "complete_task":      return _clean(handle_complete_task(msg_stripped, db))
    if intent == "bulk_set_priority":  return _clean(handle_bulk_set_priority(msg_stripped, db))
    if intent == "set_priority":       return _clean(handle_set_priority(msg_stripped, db))
    if intent == "review_priorities":  return _clean(handle_start_priority_wizard(db))
    if intent == "task_analytics":     return _clean(handle_analytics(db))
    if intent == "get_plan":           return _clean(handle_get_plan(db))
    if intent == "task_predict":       return _clean(handle_predict(msg_stripped, db))
    if intent == "delete_task":        return _clean(handle_delete_task(msg_stripped, db))
    if intent == "procrastination":    return _clean(handle_procrastination(db))
    if intent == "goal_check":         return _clean(handle_goal_check(db))
    if intent == "category_breakdown": return _clean(handle_category_breakdown(db))

    # 5. General chat → Ollama
    task_summary = build_task_context(db)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Context: {task_summary}"},
        *conversation_history[-6:],
        {"role": "user", "content": msg_stripped},
    ]

    try:
        with httpx.Client(timeout=120.0, trust_env=False) as client:
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model":    OLLAMA_MODEL,
                    "messages": messages,
                    "stream":   False,
                    "options":  {"temperature": 0.7, "top_p": 0.9, "num_predict": 256},
                },
            )
            resp.raise_for_status()
            reply = resp.json()["message"]["content"].strip()
    except httpx.ConnectError:
        reply = "⚠️ Ollama is offline. Task features still work — just ask about your tasks!"
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        reply = "💬 I'm here! Ask me to show your tasks, add one, or plan your day."

    return {
        "reply":             strip_markdown(reply),
        "intent":            intent,
        "action_taken":      None,
        "session_update":    {},
        "task_context_used": False,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  DATA ANALYST (text-to-SQL over the warehouse) + WEEKLY COGNITIVE AUDIT
# ══════════════════════════════════════════════════════════════════════════════

DATA_QUESTION_RE = re.compile(r"^\s*(/data|/sql|data:|analyst:|ask data)\s*", re.I)
AUDIT_RE = re.compile(r"\b(cognitive audit|weekly audit|weekly review|am i (too )?dependent|ai dependency)\b")


def handle_data_question(question: str, db: Session) -> dict:
    from app.analyst.sql_agent import ask

    if not question.strip():
        return {"reply": "Ask a question about the data, e.g. '/data which platform has the most night-time prompts?'",
                "intent": "data_question", "action_taken": None, "session_update": {}, "task_context_used": False}
    out = ask(question)
    if not out.get("ok"):
        reply = f"I couldn't answer that: {out.get('error')}"
    else:
        tries = len(out["attempts"])
        reply = f"{out['answer']}\n\nSQL ({tries} attempt{'s' if tries > 1 else ''}):\n{out['sql']}"
    return {"reply": reply, "intent": "data_question", "action_taken": "sql_query",
            "session_update": {}, "task_context_used": False, "data": out}


def handle_cognitive_audit(db: Session) -> dict:
    """Weekly review written by the LLM from CDI, nudge outcomes and task history."""
    from app.decision.bandit import ThompsonBandit
    from app.decision.store import bandit_history
    from app.personal_cdi import personal_cdi

    cdi = personal_cdi(db, days=7)
    prev = personal_cdi(db, days=14)
    exp = ThompsonBandit.from_history(bandit_history(db), seed=0).posterior()
    tried = {k: v for k, v in exp.items() if v["trials"] > 0}
    facts = {
        "cdi_7d": cdi.get("cdi"), "cdi_14d": prev.get("cdi"), "components": cdi.get("components"),
        "ai_minutes_7d": cdi.get("ai_minutes"), "tasks_completed_7d": cdi.get("tasks_completed"),
        "ai_minutes_per_completed_task": cdi.get("ai_minutes_per_completed_task"),
        "nudge_results": tried,
    }
    fallback = (
        f"Last 7 days: {facts['ai_minutes_7d']} AI minutes, {facts['tasks_completed_7d']} tasks completed"
        + (f", CDI {facts['cdi_7d']}" if facts["cdi_7d"] is not None else "")
        + ". " + (f"Best nudge so far: {max(tried, key=lambda k: tried[k]['mean'])}." if tried else "No nudge outcomes yet.")
    )
    try:
        with httpx.Client(timeout=90.0, trust_env=False) as client:
            r = client.post(f"{OLLAMA_BASE_URL}/api/chat", json={
                "model": OLLAMA_MODEL, "stream": False,
                "options": {"temperature": 0.4, "num_predict": 260},
                "messages": [
                    {"role": "system", "content": "You write a short, honest weekly review of how someone uses AI. "
                     "Use only the facts given. 4-6 sentences: what the numbers say, whether AI seems to be helping "
                     "them finish tasks or replacing their own thinking, which nudge worked, one concrete change "
                     "for next week. CDI is 0-100, higher = more dependent. No markdown."},
                    {"role": "user", "content": str(facts)},
                ],
            })
            r.raise_for_status()
            reply = r.json()["message"]["content"].strip()
    except Exception:
        reply = fallback
    return {"reply": reply, "intent": "cognitive_audit", "action_taken": None,
            "session_update": {}, "task_context_used": True, "data": facts}


# ══════════════════════════════════════════════════════════════════════════════
#  BACKWARDS COMPATIBILITY
# ══════════════════════════════════════════════════════════════════════════════

def query_with_memory(db: Session, user_query: str) -> str:
    return smart_chat(message=user_query, user_id=0, db=db, session_state={})["reply"]

def generate_daily_plan(db: Session) -> str:
    return smart_chat(message="plan my day", user_id=0, db=db, session_state={})["reply"]
