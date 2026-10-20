import pytest

from jarvis.scheduling import database
from jarvis.scheduling.task_service import (
    add_task, complete_task, delete_task, edit_task, get_all_tasks, set_task_status,
)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    database.close()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    database._conn = None
    yield
    database.close()
    database._conn = None


def test_task_crud_keeps_linked_deadline_reminder_in_sync():
    deadline = 4_200_000_000.0
    task_id = add_task("Draft report", "First details", priority=2, deadline=deadline)
    linked = database.execute(
        "SELECT * FROM reminders WHERE task_id=?", (task_id,)
    ).fetchone()
    assert linked["title"] == "Draft report"
    assert linked["due_at"] == deadline

    new_deadline = deadline + 60
    edit_task(task_id, title="Finish report", description="Updated", deadline=new_deadline)
    linked = database.execute(
        "SELECT * FROM reminders WHERE task_id=?", (task_id,)
    ).fetchone()
    assert linked["title"] == "Finish report"
    assert linked["description"] == "Updated"
    assert linked["due_at"] == new_deadline

    complete_task(task_id)
    linked = database.execute(
        "SELECT * FROM reminders WHERE task_id=?", (task_id,)
    ).fetchone()
    assert linked["enabled"] == 0
    assert linked["status"] == "completed"

    set_task_status(task_id, "todo")
    linked = database.execute(
        "SELECT * FROM reminders WHERE task_id=?", (task_id,)
    ).fetchone()
    assert linked["enabled"] == 1
    assert linked["completed"] == 0
    assert get_all_tasks()[0]["status"] == "todo"

    delete_task(task_id)
    assert database.execute(
        "SELECT COUNT(*) FROM reminders WHERE task_id=?", (task_id,)
    ).fetchone()[0] == 0
