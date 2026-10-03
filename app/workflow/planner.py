from sqlalchemy.orm import Session
from app.workflow.classifier import get_prioritized_tasks
from app.memory.store import get_all_memories

def build_day_context(db: Session) -> str:
    """
    Builds a plain-text context string summarizing:
    - Active tasks by quadrant
    - Top memories by importance score
    This gets sent to the LLM for plan generation.
    """
    tasks = get_prioritized_tasks(db)
    memories = get_all_memories(db)

    lines = ["=== CURRENT TASK STATE ==="]

    quadrant_labels = {
        "do_now": "DO NOW (Urgent + Important)",
        "schedule": "SCHEDULE (Important, Not Urgent)",
        "delegate": "DELEGATE (Urgent, Not Important)",
        "eliminate": "ELIMINATE (Low Priority)"
    }

    for quadrant, label in quadrant_labels.items():
        task_list = tasks.get(quadrant, [])
        if task_list:
            lines.append(f"\n{label}:")
            for t in task_list:
                deadline_str = f" | Deadline: {t.due_date}" if t.due_date else ""
                lines.append(f"  - {t.title}{deadline_str}")

    lines.append("\n=== ACTIVE MEMORIES (by importance) ===")
    top_memories = sorted(memories, key=lambda m: m.importance_score, reverse=True)[:5]
    for m in top_memories:
        lines.append(f"  [{m.category}] {m.content} (score: {m.importance_score})")

    return "\n".join(lines)
