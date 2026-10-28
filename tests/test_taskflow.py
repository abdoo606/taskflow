from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from taskflow.cli import _human_due, _parse_due, render_table, run
from taskflow.models import Priority, Status, Task
from taskflow.store import TaskStore


# ---------------------------------------------------------------- models
def test_task_rejects_blank_title():
    with pytest.raises(ValueError, match="title"):
        Task(title="   ")


@pytest.mark.parametrize("raw,expected", [("HIGH", Priority.HIGH), (" low ", Priority.LOW)])
def test_priority_parse_is_forgiving(raw, expected):
    assert Priority.parse(raw) is expected


def test_priority_parse_rejects_garbage():
    with pytest.raises(ValueError, match="invalid priority"):
        Priority.parse("urgent")


def test_overdue_logic():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert Task(title="a", due=yesterday).is_overdue is True
    assert Task(title="a", due=yesterday, status=Status.DONE).is_overdue is False
    assert Task(title="a").is_overdue is False


def test_sort_key_puts_high_priority_first():
    tasks = [Task("low", Priority.LOW), Task("high", Priority.HIGH)]
    assert sorted(tasks, key=Task.sort_key)[0].title == "high"


# ----------------------------------------------------------------- store
@pytest.fixture()
def store():
    with TaskStore(":memory:") as s:
        yield s


def test_add_assigns_incrementing_ids(store):
    a = store.add(Task("first"))
    b = store.add(Task("second"))
    assert (a.id, b.id) == (1, 2)


def test_update_status_returns_false_for_missing(store):
    assert store.update_status(999, Status.DONE) is False


def test_list_filters_by_status_and_tag(store):
    store.add(Task("write report", tags=("work",)))
    store.add(Task("buy milk", tags=("home",)))
    done = store.add(Task("ship it", tags=("work",)))
    store.update_status(done.id, Status.DONE)

    assert [t.title for t in store.list(tag="work")] == ["write report", "ship it"]
    assert [t.title for t in store.list(status=Status.DONE)] == ["ship it"]
    assert [t.title for t in store.list(search="milk")] == ["buy milk"]


def test_tag_filter_is_exact_not_substring(store):
    store.add(Task("a", tags=("workout",)))
    assert store.list(tag="work") == []


def test_counts_and_overdue(store):
    store.add(Task("x"))
    store.add(Task("y"))
    store.add(Task("late", due=(date.today() - timedelta(days=2)).isoformat()))
    assert store.counts_by_status() == {"todo": 3}
    assert len(store.overdue()) == 1


def test_delete(store):
    t = store.add(Task("temp"))
    assert store.delete(t.id) is True
    assert store.delete(t.id) is False
    assert store.list() == []


def test_data_survives_reopen(tmp_path):
    path = tmp_path / "t.db"
    with TaskStore(path) as s:
        s.add(Task("persisted", tags=("db",)))
    with TaskStore(path) as s:
        assert [t.title for t in s.list()] == ["persisted"]
        assert s.list()[0].tags == ("db",)


# ------------------------------------------------------------------- cli
def test_parse_due_relative():
    assert _parse_due("+3") == (date.today() + timedelta(days=3)).isoformat()
    assert _parse_due(None) is None
    with pytest.raises(ValueError):
        _parse_due("31/12/2024")


def test_human_due_labels():
    today = date.today()
    assert _human_due(today.isoformat()) == "today"
    assert _human_due((today + timedelta(days=2)).isoformat()) == "in 2d"
    assert _human_due((today - timedelta(days=2)).isoformat()) == "2d late"
    assert _human_due(None) == "-"


def test_render_table_empty_message():
    assert "no tasks" in render_table([])


def test_cli_add_list_json(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    assert run(["--db", db, "add", "تعلم بايثون", "-p", "high", "-t", "study"]) == 0
    capsys.readouterr()
    assert run(["--db", db, "list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["title"] == "تعلم بايثون"
    assert payload[0]["priority"] == "high"


def test_cli_missing_id_exits_nonzero(tmp_path, capsys):
    assert run(["--db", str(tmp_path / "c.db"), "done", "42"]) == 1
    assert "no task" in capsys.readouterr().err


def test_cli_rejects_bad_priority(tmp_path):
    with pytest.raises(SystemExit):
        run(["--db", str(tmp_path / "c.db"), "add", "x", "-p", "nope"])


def test_cli_stats_output(tmp_path, capsys):
    db = str(tmp_path / "s.db")
    run(["--db", db, "add", "one"])
    run(["--db", db, "add", "two"])
    run(["--db", db, "done", "1"])
    capsys.readouterr()
    assert run(["--db", db, "stats"]) == 0
    out = capsys.readouterr().out
    assert "total    : 2" in out
    assert "done     : 1" in out


def test_cli_export_csv(tmp_path):
    db = str(tmp_path / "e.db")
    out = tmp_path / "tasks.csv"
    run(["--db", db, "add", "export me"])
    assert run(["--db", db, "export", "--format", "csv", "-o", str(out)]) == 0
    assert "export me" in out.read_text(encoding="utf-8")
