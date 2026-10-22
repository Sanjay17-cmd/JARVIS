import json
import time

import pytest

from jarvis.ai.agent import AIAgent
from jarvis.ai.tools import ToolRegistry
from jarvis.scheduling import database


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    database.close()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    database._conn = None
    yield
    database.close()
    database._conn = None


class Gateway:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def context_fingerprint(self, _prompt):
        return "fingerprint", "conversation-1"

    def generate(
        self, prompt, on_chunk=None, cancel_event=None, on_reset=None,
        use_cache=True,
    ):
        self.prompts.append(prompt)
        return self.responses.pop(0)


def plan(action=None, response=""):
    return json.dumps({"action": action, "response": response})


def test_agent_calls_validated_registry_and_returns_persisted_record():
    gateway = Gateway(plan({
        "name": "task_create",
        "arguments": {"title": "Finish report", "priority": 3},
    }))
    registry = ToolRegistry()
    chunks = []
    agent = AIAgent(gateway, registry)

    response = agent.generate(
        "Create a task to finish my report", chunks.append,
    )

    assert response.startswith("Please confirm:")
    assert "Finish report" in response
    assert database.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert chunks == [response]
    assert "task_create" in gateway.prompts[0]
    completed = agent.generate("yes", chunks.append)
    task = database.execute(
        "SELECT title,priority FROM tasks"
    ).fetchone()
    assert tuple(task) == ("Finish report", 3)
    assert "Created task" in completed
    assert chunks[-1] == completed


def test_agent_returns_normal_response_without_running_a_tool():
    gateway = Gateway("Here's a short joke.")
    response = AIAgent(gateway, ToolRegistry()).generate("Tell me a joke")
    assert response == "Here's a short joke."
    assert gateway.prompts == ["Tell me a joke"]
    assert database.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_destructive_action_requires_confirmation_and_cancel_is_non_mutating():
    from jarvis.scheduling import task_service

    task_id = task_service.add_task("Delete only if confirmed")
    gateway = Gateway(
        plan({
            "name": "task_delete",
            "arguments": {"task_id": task_id, "confirmed": True},
        }),
        plan(response="unused"),
    )
    agent = AIAgent(gateway, ToolRegistry())

    prompt = agent.generate("Delete my task")
    assert prompt.startswith("Please confirm:")
    assert database.execute(
        "SELECT 1 FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    cancelled = agent.generate("cancel")
    assert cancelled == "Cancelled. No changes were made."
    assert database.execute(
        "SELECT 1 FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    assert len(gateway.prompts) == 1


def test_destructive_action_executes_only_after_explicit_confirmation():
    from jarvis.scheduling import task_service

    task_id = task_service.add_task("Confirm deletion")
    gateway = Gateway(plan({
        "name": "task_delete",
        "arguments": {"task_id": task_id, "confirmed": True},
    }))
    agent = AIAgent(gateway, ToolRegistry())

    assert agent.generate("Delete my task").startswith("Please confirm:")
    result = agent.generate("confirm")
    assert "Deleted task" in result
    assert not database.execute(
        "SELECT 1 FROM tasks WHERE id=?", (task_id,)
    ).fetchone()


def test_pending_action_cannot_be_replaced_by_another_request():
    gateway = Gateway(
        plan({
            "name": "task_create",
            "arguments": {"title": "Keep this pending"},
        }),
        plan({
            "name": "task_create",
            "arguments": {"title": "Must not be planned"},
        }),
    )
    agent = AIAgent(gateway, ToolRegistry())
    assert agent.generate(
        "Create a task to keep this pending"
    ).startswith("Please confirm:")

    reply = agent.generate("Actually, create another task")

    assert "Please answer yes or no" in reply
    assert len(gateway.prompts) == 1
    assert database.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_application_launch_waits_for_explicit_confirmation():
    calls = []
    gateway = Gateway(plan({
        "name": "app_open",
        "arguments": {"application": "notepad"},
    }))
    registry = ToolRegistry(
        open_application=lambda app: calls.append(app) or "Opening notepad."
    )
    agent = AIAgent(gateway, registry)

    prompt = agent.generate("Open Notepad")
    assert "open application 'notepad'" in prompt
    assert calls == []
    assert "Opening notepad" in agent.generate("yeah")
    assert calls == ["notepad"]


def test_clipboard_write_waits_for_explicit_approval():
    clipboard = []
    gateway = Gateway(plan({
        "name": "clipboard_write",
        "arguments": {"text": "A generated answer to copy."},
    }))
    registry = ToolRegistry(
        write_clipboard=lambda text: clipboard.append(text) or True
    )
    agent = AIAgent(gateway, registry)

    confirmation = agent.generate("Write a short answer and copy it to clipboard")

    assert confirmation.startswith("Please confirm:")
    assert "A generated answer to copy." in confirmation
    assert clipboard == []

    result = agent.generate("yes")

    assert clipboard == ["A generated answer to copy."]
    assert "Copied" in result


def test_cancelled_clipboard_write_does_not_change_clipboard():
    clipboard = ["existing clipboard contents"]
    gateway = Gateway(plan({
        "name": "clipboard_write",
        "arguments": {"text": "New generated contents."},
    }))
    registry = ToolRegistry(
        write_clipboard=lambda text: clipboard.append(text) or True
    )
    agent = AIAgent(gateway, registry)

    assert agent.generate("Copy a generated summary to clipboard").startswith(
        "Please confirm:"
    )
    assert agent.generate("no") == "Cancelled. No changes were made."
    assert clipboard == ["existing clipboard contents"]


def test_reminder_creation_is_staged_until_voice_or_text_approval():
    due_at = time.time() + 1800
    gateway = Gateway(plan({
        "name": "reminder_create",
        "arguments": {
            "title": "Drink water",
            "due_at": due_at,
            "description": "",
            "recurrence": "",
        },
    }))
    agent = AIAgent(gateway, ToolRegistry())

    prompt = agent.generate("Remind me in 30 minutes to drink water")
    assert prompt.startswith("Please confirm:")
    assert database.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0

    result = agent.generate("yes")

    reminder = database.execute("SELECT title,due_at FROM reminders").fetchone()
    assert reminder["title"] == "Drink water"
    assert reminder["due_at"] == due_at
    assert "Created reminder" in result


def test_duplicate_matching_tasks_trigger_clarification_before_action():
    from jarvis.scheduling import task_service

    first_id = task_service.add_task("Submit DSA assignment")
    second_id = task_service.add_task("Submit DSA assignment")
    gateway = Gateway(plan({
        "name": "task_complete",
        "arguments": {"task_id": second_id},
    }))
    agent = AIAgent(gateway, ToolRegistry())

    answer = agent.generate("Mark Submit DSA assignment complete")

    assert "multiple task records" in answer
    assert str(first_id) in answer and str(second_id) in answer
    assert database.execute(
        "SELECT COUNT(*) FROM tasks WHERE status='todo'"
    ).fetchone()[0] == 2


def test_follow_up_reference_loads_conversation_records_for_real_update():
    from jarvis.scheduling import task_service

    task_id = task_service.add_task("Project report")
    deadline = time.time() + 86400
    gateway = Gateway(plan({
        "name": "task_update",
        "arguments": {"task_id": task_id, "deadline": deadline},
    }))
    agent = AIAgent(gateway, ToolRegistry())

    prompt = agent.generate("Move it to Friday")

    persisted = database.execute(
        "SELECT deadline FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    assert prompt.startswith("Please confirm:")
    assert persisted["deadline"] is None
    result = agent.generate("yes")
    persisted = database.execute(
        "SELECT deadline FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    assert persisted["deadline"] == deadline
    assert "Project report" in gateway.prompts[0]
    assert "task_update" in gateway.prompts[0]
    assert "Project report" in result
