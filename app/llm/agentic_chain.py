# app/llm/agentic_chain.py
#
# Tool-calling agent for the chat. Instead of regex intent routing, the LLM
# reads the message, decides which tools (the existing task handlers) to call
# and with what arguments, sees their results, and writes the reply itself.
#
# If Ollama is unreachable or the model can't do tool calling, agentic_chat()
# returns None and the caller falls back to the rule-based smart_chat().

import json
import logging
import os
import time
from datetime import date, datetime
from typing import Callable, Optional

import httpx
from sqlalchemy.orm import Session

from app.llm.agent import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    PRIORITY_EMOJI,
    SYSTEM_PROMPT,
    compute_auto_priority,
    extract_task_from_message,
    get_all_pending_tasks,
    handle_analytics,
    handle_category_breakdown,
    handle_cognitive_audit,
    handle_complete_task,
    handle_data_question,
    handle_delete_task,
    handle_get_plan,
    handle_goal_check,
    handle_list_tasks,
    handle_predict,
    handle_procrastination,
    handle_set_priority,
    handle_start_priority_wizard,
    parse_deadline,
    resolve_priority,
    smart_follow_up,
    strip_markdown,
)
from app.ml.task_predictor import predictor
from app.models import Task

logger = logging.getLogger(__name__)

AGENT_MODEL     = os.getenv("OLLAMA_AGENT_MODEL", OLLAMA_MODEL)
AGENT_ENABLED   = os.getenv("COGNITIVE_AGENT", "1") != "0"
MAX_TOOL_ROUNDS = 5
TIME_BUDGET_S   = 150   # frontend waits 180s for /ai/chat

# Set once Ollama tells us the model can't do tools, so we stop asking.
_tools_unsupported: Optional[str] = None
# After a failed connect, skip the agent for a while: on Windows a refused
# connection to localhost takes ~2s per address, which would slow every message.
OLLAMA_RETRY_S = 60
_ollama_down_until = 0.0

PRIORITIES = ["Critical", "High", "Medium", "Low"]
CATEGORIES = ["Development", "Learning", "Personal", "Finance", "Work", "Other"]


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL IMPLEMENTATIONS
#  Each takes (db, **args) and returns a handler-style dict with a "reply".
#  Most wrap an existing handler so the business logic lives in one place.
# ══════════════════════════════════════════════════════════════════════════════

def _parse_due(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return parse_deadline(value)   # "friday", "tomorrow", "in 3 days"...


def tool_create_task(db: Session, title: str, priority: Optional[str] = None,
                     category: Optional[str] = None, due_date: Optional[str] = None,
                     estimated_minutes: Optional[int] = None, notes: Optional[str] = None) -> dict:
    # Keyword-based defaults for anything the model didn't specify
    defaults, _ = extract_task_from_message(title)
    due = _parse_due(due_date)

    task = Task(
        title=(title or "New Task").strip()[:200],
        category=category if category in CATEGORIES else defaults["category"],
        estimated_minutes=int(estimated_minutes) if estimated_minutes else defaults["estimated_minutes"],
        due_date=datetime.combine(due, datetime.min.time()) if due else None,
        notes=notes or "",
        status="pending",
    )
    priority = (priority or "").capitalize()
    task.priority = priority if priority in PRIORITIES else "Medium"
    if not priority and due:
        task.priority = compute_auto_priority(task)
        if task.priority == "Overdue":
            task.priority = "Critical"

    db.add(task)
    db.commit()
    db.refresh(task)

    due_str = f", due {task.due_date.date()}" if task.due_date else ""
    return {
        "reply": (
            f"Created task #{task.id} '{task.title}' — {PRIORITY_EMOJI.get(task.priority, '')} "
            f"{task.priority}, {task.category}, ~{task.estimated_minutes} min{due_str}."
            + smart_follow_up(db, "task_created", task.id)
        ),
        "intent": "create_task",
        "action_taken": {
            "action": "task_created", "task_id": task.id, "task_title": task.title,
            "priority": task.priority, "category": task.category,
            "estimated_minutes": task.estimated_minutes,
            "due_date": task.due_date.date().isoformat() if task.due_date else None,
        },
        "session_update": {},
    }


def tool_list_tasks(db: Session, filter: str = "pending") -> dict:
    return handle_list_tasks(filter or "pending", db)


def tool_complete_task(db: Session, task_id: int) -> dict:
    return handle_complete_task(f"task #{int(task_id)}", db)


def tool_set_priority(db: Session, task_id: int, priority: str) -> dict:
    return handle_set_priority(f"#{int(task_id)} {priority}", db)


def tool_delete_task(db: Session, task_id: int) -> dict:
    return handle_delete_task(f"#{int(task_id)}", db)


def tool_estimate_time(db: Session, task_id: Optional[int] = None,
                       description: Optional[str] = None) -> dict:
    if task_id:
        return handle_predict(f"#{int(task_id)}", db)
    # handle_predict treats any digit in free text as a task ID, so the
    # description path is done here instead.
    if not predictor.is_trained:
        done = db.query(Task).filter(Task.status == "completed").count()
        return {"reply": f"The time predictor needs {max(0, 5 - done)} more completed task(s) before it can estimate."}
    task_data, _ = extract_task_from_message(description or "")
    temp = Task(**{k: v for k, v in task_data.items() if k != "due_date"})
    return {"reply": f"ML estimate for '{task_data['title']}': ~{predictor.predict_single(temp)} min "
                     f"({task_data['category']}, {task_data['priority']})."}


def tool_ask_data(db: Session, question: str) -> dict:
    return handle_data_question(question, db)


TOOL_FUNCS: dict[str, Callable[..., dict]] = {
    "create_task":            tool_create_task,
    "list_tasks":             tool_list_tasks,
    "complete_task":          tool_complete_task,
    "set_priority":           tool_set_priority,
    "delete_task":            tool_delete_task,
    "plan_day":               lambda db: handle_get_plan(db),
    "productivity_stats":     lambda db: handle_analytics(db),
    "procrastination_report": lambda db: handle_procrastination(db),
    "goal_check":             lambda db: handle_goal_check(db),
    "category_breakdown":     lambda db: handle_category_breakdown(db),
    "estimate_time":          tool_estimate_time,
    "start_priority_review":  lambda db: handle_start_priority_wizard(db),
    "ai_usage_audit":         lambda db: handle_cognitive_audit(db),
    "ask_data":               tool_ask_data,
}


def _fn(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }


TASK_ID = {"task_id": {"type": "integer", "description": "The task number, e.g. 12 for #12"}}

TOOLS = [
    _fn("create_task", "Add a new task to the user's list.", {
        "title":             {"type": "string", "description": "Short task title, without dates or priority words"},
        "priority":          {"type": "string", "enum": PRIORITIES, "description": "Only if the user implies urgency/importance"},
        "category":          {"type": "string", "enum": CATEGORIES},
        "due_date":          {"type": "string", "description": "YYYY-MM-DD, if the user gave a deadline"},
        "estimated_minutes": {"type": "integer", "description": "Only if the user said how long it takes"},
        "notes":             {"type": "string"},
    }, ["title"]),
    _fn("list_tasks", "Show the user's tasks.", {
        "filter": {"type": "string", "enum": ["pending", "completed", "critical", "high", "low"]},
    }),
    _fn("complete_task", "Mark a task as done.", TASK_ID, ["task_id"]),
    _fn("set_priority", "Change a task's priority.", {
        **TASK_ID, "priority": {"type": "string", "enum": PRIORITIES},
    }, ["task_id", "priority"]),
    _fn("delete_task", "Permanently delete a task. Only when the user explicitly asks to delete/remove it.",
        TASK_ID, ["task_id"]),
    _fn("plan_day", "Build today's ordered plan from pending tasks, personalised to the user's patterns."),
    _fn("productivity_stats", "Completion rate, streaks, time invested and predictor accuracy."),
    _fn("procrastination_report", "Tasks the user keeps putting off."),
    _fn("goal_check", "Progress against today's daily task goal."),
    _fn("category_breakdown", "Where the user's time goes, by category."),
    _fn("estimate_time", "ML estimate of how long a task will take. Give task_id for an existing task, "
                         "or description for a hypothetical one.", {
        **TASK_ID, "description": {"type": "string"},
    }),
    _fn("start_priority_review", "Start the one-by-one priority review wizard over all pending tasks."),
    _fn("ai_usage_audit", "Weekly audit of the user's AI-tool usage and dependency patterns."),
    _fn("ask_data", "Answer an analytical question about the user's AI-usage data warehouse with SQL.", {
        "question": {"type": "string"},
    }, ["question"]),
]


# ══════════════════════════════════════════════════════════════════════════════
#  PROMPT
# ══════════════════════════════════════════════════════════════════════════════

def _task_snapshot(db: Session, limit: int = 25) -> str:
    pending = get_all_pending_tasks(db)
    if not pending:
        return "The user has no pending tasks."
    lines = [f"Pending tasks ({len(pending)}):"]
    for t in pending[:limit]:
        due = f", due {t.due_date.date()}" if t.due_date else ""
        lines.append(f"#{t.id} {t.title} [{resolve_priority(t)}, {t.category}{due}]")
    if len(pending) > limit:
        lines.append(f"...and {len(pending) - limit} more (use list_tasks).")
    return "\n".join(lines)


def _system_prompt(db: Session) -> str:
    now = datetime.now()
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Today is {now.strftime('%A %Y-%m-%d')}, {now.strftime('%H:%M')}.\n\n"
        "You manage the user's tasks through tools. Rules:\n"
        "- Use a tool whenever the user wants to see or change their tasks, plans or stats. "
        "Never claim you did something without calling the tool.\n"
        "- You can call several tools, e.g. create multiple tasks from one message.\n"
        "- Convert relative deadlines ('friday', 'tomorrow') to YYYY-MM-DD using today's date.\n"
        "- Refer to tasks by number (#12). If it's unclear which task the user means, ask.\n"
        "- When a tool returns a list or plan, show it to the user; don't summarise it away.\n"
        "- For small talk or advice, just answer — no tool needed.\n"
        "- Reply in plain text (no markdown headings or bold).\n\n"
        f"{_task_snapshot(db)}"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  OLLAMA CALL + LOOP
# ══════════════════════════════════════════════════════════════════════════════

class AgentUnavailable(Exception):
    """Ollama is down, or the model can't do tool calling."""


def _ollama_chat(messages: list, timeout: float) -> dict:
    """One /api/chat round. Returns the assistant message dict."""
    global _tools_unsupported, _ollama_down_until
    try:
        # trust_env=False: Ollama is local, never route it through HTTP(S)_PROXY
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model":    AGENT_MODEL,
                    "messages": messages,
                    "tools":    TOOLS,
                    "stream":   False,
                    "options":  {"temperature": 0.3, "num_predict": 700},
                },
            )
    except httpx.ConnectError as e:
        _ollama_down_until = time.monotonic() + OLLAMA_RETRY_S
        raise AgentUnavailable(f"Ollama unreachable at {OLLAMA_BASE_URL}") from e

    if resp.status_code == 400 and "does not support tools" in resp.text:
        _tools_unsupported = AGENT_MODEL
        logger.warning(f"[Agent] Model '{AGENT_MODEL}' can't do tool calling — using rule-based chat. "
                       "Set OLLAMA_AGENT_MODEL to e.g. qwen2.5:7b or llama3.1:8b.")
        raise AgentUnavailable("model lacks tool support")
    if resp.status_code == 404:
        raise AgentUnavailable(f"model '{AGENT_MODEL}' not pulled — run: ollama pull {AGENT_MODEL}")
    resp.raise_for_status()
    return resp.json()["message"]


def _run_tool(name: str, args, db: Session) -> dict:
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return {"reply": f"Unknown tool '{name}'."}
    if isinstance(args, str):   # some models send JSON-encoded arguments
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            args = {}
    try:
        return fn(db, **(args or {}))
    except TypeError as e:      # wrong/missing arguments from the model
        return {"reply": f"Tool '{name}' was called with bad arguments: {e}"}
    except Exception as e:
        db.rollback()
        logger.exception(f"[Agent] Tool {name} failed")
        return {"reply": f"Tool '{name}' failed: {e}"}


def agentic_chat(
    message: str,
    db: Session,
    conversation_history: list | None = None,
) -> Optional[dict]:
    """
    Answer `message` with the tool-calling loop.
    Returns None when the agent can't run, so the caller can fall back to smart_chat().
    """
    if not AGENT_ENABLED or _tools_unsupported == AGENT_MODEL or time.monotonic() < _ollama_down_until:
        return None

    messages = [
        {"role": "system", "content": _system_prompt(db)},
        *[m for m in (conversation_history or [])[-8:] if m.get("role") in ("user", "assistant")],
        {"role": "user", "content": message.strip()},
    ]

    deadline       = time.monotonic() + TIME_BUDGET_S
    tool_results   = []     # (name, result dict) in call order
    reply          = None

    try:
        for _ in range(MAX_TOOL_ROUNDS + 1):
            remaining = deadline - time.monotonic()
            if remaining < 5:
                break
            msg   = _ollama_chat(messages, timeout=remaining)
            calls = msg.get("tool_calls") or []
            if not calls:
                reply = (msg.get("content") or "").strip()
                break

            messages.append(msg)
            for call in calls:
                fn     = call.get("function", {})
                name   = fn.get("name", "")
                result = _run_tool(name, fn.get("arguments"), db)
                tool_results.append((name, result))
                logger.info(f"[Agent] {name}({fn.get('arguments')})")
                messages.append({"role": "tool", "tool_name": name, "content": result.get("reply", "")})
    except AgentUnavailable as e:
        if not tool_results:
            logger.info(f"[Agent] Falling back to rule-based chat: {e}")
            return None
    except Exception as e:
        # Tools may already have changed the DB, so don't fall back (it would
        # redo them) — report what was done instead.
        logger.error(f"[Agent] LLM error: {e}")
        if not tool_results:
            return None

    if not reply:
        # Out of rounds/time, or the LLM failed after tools ran: show raw tool output.
        reply = "\n\n".join(r.get("reply", "") for _, r in tool_results) or "Sorry, I couldn't finish that."

    session_update = {}
    action_taken   = None
    intent         = "general_chat"
    for name, r in tool_results:
        session_update.update(r.get("session_update") or {})
        action_taken = r.get("action_taken") or action_taken
        intent       = r.get("intent") or intent

    return {
        "reply":             strip_markdown(reply),
        "intent":            intent,
        "action_taken":      action_taken,
        "session_update":    session_update,
        "task_context_used": True,
        "tools_used":        [name for name, _ in tool_results],
    }
