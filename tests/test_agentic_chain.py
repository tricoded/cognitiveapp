"""Tool-calling agent tests. Ollama is faked by patching _ollama_chat."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.llm import agentic_chain
from app.llm.agent import smart_chat
from app.models import Task


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def reset_agent(monkeypatch):
    monkeypatch.setattr(agentic_chain, "_tools_unsupported", None)
    monkeypatch.setattr(agentic_chain, "_ollama_down_until", 0.0)
    monkeypatch.setattr(agentic_chain, "AGENT_ENABLED", True)


def fake_ollama(monkeypatch, script):
    """script: list of assistant messages (or exceptions) returned in order."""
    seen = []

    def _chat(messages, timeout):
        seen.append(list(messages))
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(agentic_chain, "_ollama_chat", _chat)
    return seen


def call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def say(text):
    return {"role": "assistant", "content": text}


def test_agent_creates_task_from_structured_args(monkeypatch, db):
    seen = fake_ollama(monkeypatch, [
        call("create_task", title="Finish essay", priority="High", due_date="2026-10-02", estimated_minutes=90),
        say("Added 'Finish essay' for Friday, high priority."),
    ])

    r = agentic_chain.agentic_chat("remind me to finish the essay by friday, it's important, ~1.5h", db)

    task = db.query(Task).one()
    assert (task.title, task.priority, task.estimated_minutes) == ("Finish essay", "High", 90)
    assert task.due_date.date().isoformat() == "2026-10-02"
    assert r["reply"] == "Added 'Finish essay' for Friday, high priority."
    assert r["action_taken"]["task_id"] == task.id
    assert r["tools_used"] == ["create_task"]
    # The tool result was fed back to the model before its final answer
    assert seen[1][-1]["role"] == "tool" and "Finish essay" in seen[1][-1]["content"]


def test_multiple_tool_calls_in_one_turn(monkeypatch, db):
    both = {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "create_task", "arguments": {"title": "Buy milk"}}},
        {"function": {"name": "create_task", "arguments": '{"title": "Call mom"}'}},   # JSON-string args
    ]}
    fake_ollama(monkeypatch, [both, say("Added both.")])

    agentic_chain.agentic_chat("add buy milk and call mom", db)

    assert sorted(t.title for t in db.query(Task)) == ["Buy milk", "Call mom"]


def test_due_date_without_priority_sets_auto_priority(monkeypatch, db):
    from datetime import date, timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    fake_ollama(monkeypatch, [call("create_task", title="Pay rent", due_date=tomorrow), say("ok")])

    agentic_chain.agentic_chat("pay rent tomorrow", db)

    assert db.query(Task).one().priority == "Critical"


def test_ollama_down_returns_none_and_smart_chat_falls_back(monkeypatch, db):
    fake_ollama(monkeypatch, [agentic_chain.AgentUnavailable("down")])
    assert agentic_chain.agentic_chat("hello", db) is None

    fake_ollama(monkeypatch, [agentic_chain.AgentUnavailable("down")])
    r = smart_chat("add a task to water the plants", user_id=0, db=db, session_state={})
    assert r["intent"] == "create_task"
    assert db.query(Task).one().title.lower().startswith("water the plants")


def test_model_without_tool_support_is_remembered(monkeypatch, db):
    calls = fake_ollama(monkeypatch, [])
    monkeypatch.setattr(agentic_chain, "_tools_unsupported", agentic_chain.AGENT_MODEL)
    assert agentic_chain.agentic_chat("hi", db) is None
    assert calls == []   # didn't even try


def test_llm_failure_after_tool_ran_does_not_redo_the_action(monkeypatch, db):
    fake_ollama(monkeypatch, [call("create_task", title="Gym"), RuntimeError("timeout")])

    r = agentic_chain.agentic_chat("add gym", db)

    assert db.query(Task).count() == 1          # not created twice via fallback
    assert "Gym" in r["reply"]


def test_bad_tool_arguments_are_reported_to_the_model(monkeypatch, db):
    seen = fake_ollama(monkeypatch, [call("complete_task", id=3), say("Which task number?")])

    r = agentic_chain.agentic_chat("done with it", db)

    assert "bad arguments" in seen[1][-1]["content"]
    assert r["reply"] == "Which task number?"


def test_priority_review_session_update_is_passed_through(monkeypatch, db):
    db.add(Task(title="A", status="pending"))
    db.commit()
    fake_ollama(monkeypatch, [call("start_priority_review"), say("Let's review! Reply C/H/M/L/S.")])

    r = agentic_chain.agentic_chat("help me sort my priorities", db)

    assert r["session_update"]["priority_review_active"] is True


def test_plain_chat_needs_no_tools(monkeypatch, db):
    fake_ollama(monkeypatch, [say("Take a 10 minute walk, then start with the smallest task.")])
    r = agentic_chain.agentic_chat("I feel overwhelmed", db)
    assert r["tools_used"] == [] and "walk" in r["reply"]


@pytest.mark.parametrize("status,body,cached", [
    (400, '{"error":"registry.ollama.ai/library/mistral does not support tools"}', True),
    (404, '{"error":"model not found"}', False),
])
def test_ollama_http_errors_map_to_unavailable(monkeypatch, db, status, body, cached):
    import httpx
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, json: httpx.Response(status, text=body))

    assert agentic_chain.agentic_chat("hi", db) is None
    assert (agentic_chain._tools_unsupported == agentic_chain.AGENT_MODEL) is cached


def test_ollama_connection_refused_falls_back(monkeypatch, db):
    import httpx
    def refuse(self, url, json):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx.Client, "post", refuse)

    assert agentic_chain.agentic_chat("hi", db) is None
    assert agentic_chain._tools_unsupported is None   # not permanent; Ollama may come up

    # ...but the next message skips the slow connect attempt for a while
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: pytest.fail("should not retry yet"))
    assert agentic_chain.agentic_chat("hi again", db) is None


def test_system_prompt_includes_date_and_pending_tasks(monkeypatch, db):
    db.add(Task(title="Write report", status="pending", priority="High"))
    db.commit()
    seen = fake_ollama(monkeypatch, [say("hi")])

    agentic_chain.agentic_chat("hi", db)

    system = seen[0][0]["content"]
    assert "Today is" in system and "Write report" in system
