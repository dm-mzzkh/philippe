"""DB-facing logic: field→column mapping, SQL build, catalog, resolution,
context — all with a fake DB-API connection (no live Postgres)."""

import datetime as dt

import pytest

from philippe.context import resolve_context
from philippe.db.catalog import SqlCatalog
from philippe.db.resolve import form_needs_db, resolve_form
from philippe.dialog import Engine, Session, Show
from philippe.dialog.engine import SUBMIT
from philippe.fields import get_field_type
from philippe.fields.base import Input
from philippe.fields.select import OptionSource, SelectSpec
from philippe.forms import FormError, load_form
from philippe.forms.models import ContextColumn, FieldSpec, FormSpec


# --- fake DB-API connection ------------------------------------------------

class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []  # list of (sql, params)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, rows=None):
        self.cursor_obj = FakeCursor(rows or [])
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


# --- field → column mapping ------------------------------------------------

def test_repeat_maps_to_period_and_every():
    spec = get_field_type("repeat").spec_model(key="schedule", type="repeat", label="x")
    from philippe.fields.repeat import Recurrence

    ft = get_field_type("repeat")
    assert ft.columns(spec) == ["period", "every"]
    assert ft.to_columns(spec, Recurrence("week", 3)) == {"period": "week", "every": 3}


def test_column_override_renames_target_column():
    spec = SelectSpec(key="task", type="select", label="x",
                      column="task_id", options=["a"])
    ft = get_field_type("select")
    assert ft.columns(spec) == ["task_id"]
    assert ft.to_columns(spec, "a") == {"task_id": "a"}


def test_engine_builds_column_keyed_record(tmp_path):
    form = load_form(_write(tmp_path, """
        name: t
        title: T
        table: tasks
        fields:
          - {key: title, type: title, label: Title}
          - {key: schedule, type: repeat, label: How often}
          - {key: active, type: bool, label: Active, default: true}
    """))
    e = Engine()
    s = Session(form=form)
    e.start(s)
    e.step(s, Input(text="Vacuum"))
    e.step(s, Input(button="week"))
    e.step(s, Input(button="3"))            # repeat done
    out = e.step(s, Input(button="yes"))    # bool → review
    done = e.step(s, Input(button=SUBMIT))
    assert done.record == {"title": "Vacuum", "period": "week", "every": 3, "active": True}


# --- SQL sink --------------------------------------------------------------

def test_sql_sink_casts_each_value_to_its_column_type():
    from philippe.sink import SqlSink

    # fetchall() answers the information_schema introspection query
    conn = FakeConn(rows=[("task_id", "int4"), ("done_at", "date"),
                          ("comment", "text")])
    form = FormSpec(name="log", title="L", table="logs", fields=[])
    record = {"task_id": 5, "done_at": dt.date(2026, 6, 11), "comment": None}
    SqlSink(conn).save(form, record)

    introspect_sql = conn.cursor_obj.executed[0][0]
    assert "information_schema.columns" in introspect_sql

    insert_sql, params = conn.cursor_obj.executed[1]
    assert insert_sql == ('INSERT INTO "logs" ("task_id", "done_at", "comment") '
                          'VALUES (%s::int4, %s::date, %s::text)')
    assert params == [5, dt.date(2026, 6, 11), None]
    assert conn.commits == 1


def test_sql_sink_casts_enum_column():
    """The point of casting: a Python str into an ENUM column."""
    from philippe.sink import SqlSink

    conn = FakeConn(rows=[("title", "text"), ("period", "task_period"),
                          ("every", "int4")])
    form = FormSpec(name="task", title="T", table="tasks", fields=[])
    SqlSink(conn).save(form, {"title": "Vacuum", "period": "week", "every": 3})

    insert_sql, params = conn.cursor_obj.executed[1]
    assert insert_sql == ('INSERT INTO "tasks" ("title", "period", "every") '
                          'VALUES (%s::text, %s::task_period, %s::int4)')
    assert params == ["Vacuum", "week", 3]


def test_sql_sink_rolls_back_on_error():
    from philippe.sink import SqlSink

    class FailingInsertCursor(FakeCursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if sql.startswith("INSERT"):
                raise RuntimeError("insert boom")

    conn = FakeConn(rows=[("a", "int4")])
    conn.cursor_obj = FailingInsertCursor([("a", "int4")])
    form = FormSpec(name="log", title="L", table="logs", fields=[])
    with pytest.raises(RuntimeError):
        SqlSink(conn).save(form, {"a": 1})
    assert conn.rollbacks == 1


# --- catalog ---------------------------------------------------------------

def test_sql_catalog_queries_and_returns_label_value_pairs():
    conn = FakeConn(rows=[("dishes", 1), ("floor", 2)])
    source = OptionSource(table="tasks", value="id", label="title",
                          where="active = true", order_by="title")
    choices = SqlCatalog(conn).options(source)
    assert choices == [("dishes", 1), ("floor", 2)]

    sql = conn.cursor_obj.executed[0][0]
    assert '"title" AS label' in sql and '"id" AS value' in sql
    assert 'FROM "tasks"' in sql
    assert "WHERE active = true" in sql
    assert "ORDER BY title" in sql


# --- form resolution -------------------------------------------------------

class FakeCatalog:
    def __init__(self, choices):
        self.choices = choices

    def options(self, source):
        return self.choices


def test_resolve_form_fills_dynamic_select_choices(tmp_path):
    form = load_form(_write(tmp_path, _LOG_FORM))
    resolved = resolve_form(form, FakeCatalog([("dishes", 1), ("floor", 2)]))
    select = resolved.fields[0]
    assert select.choices() == [("dishes", 1), ("floor", 2)]
    # the original form is untouched (per-dialog copy)
    assert form.fields[0]._choices is None


def test_resolve_form_without_catalog_raises(tmp_path):
    form = load_form(_write(tmp_path, _LOG_FORM))
    with pytest.raises(FormError, match="no database is configured"):
        resolve_form(form, None)


def test_form_needs_db_detects_dynamic_and_context(tmp_path):
    log = load_form(_write(tmp_path, _LOG_FORM))
    assert form_needs_db(log) is True
    static = load_form(_write(tmp_path, """
        name: t
        title: T
        fields:
          - {key: s, type: select, label: S, options: [a, b]}
    """))
    assert form_needs_db(static) is False


# --- dynamic select through the engine -------------------------------------

def test_dynamic_select_shows_label_stores_value(tmp_path):
    form = resolve_form(load_form(_write(tmp_path, _LOG_FORM)),
                        FakeCatalog([("dishes", 1), ("floor", 2)]))
    e = Engine()
    s = Session(form=form)
    out = e.start(s)
    # buttons show titles, payloads are the ids
    assert out.prompt.buttons[0][0].label == "dishes"
    assert out.prompt.buttons[0][0].value == "1"

    e.step(s, Input(button="2"))            # pick "floor" (id 2)
    e.step(s, Input(button="rel:0"))        # date: today
    out = e.step(s, Input(button="__skip__"))  # skip comment → review
    # review button shows the human label, not the id
    assert out.prompt.buttons[0][0].label.startswith("What did you do?: floor")

    done = e.step(s, Input(button=SUBMIT))
    assert done.record["task_id"] == 2      # stored value is the id
    assert done.record["done_at"] == dt.date.today()
    assert done.record["comment"] is None


# --- context ---------------------------------------------------------------

def test_resolve_context_maps_sources_to_columns():
    columns = [ContextColumn(column="user_id", **{"from": "user_id"}),
               ContextColumn(column="user_name", **{"from": "user_name"})]
    available = {"user_id": 777, "user_name": "@bob", "chat_id": 9}
    assert resolve_context(columns, available) == {"user_id": 777, "user_name": "@bob"}


def test_resolve_context_unknown_source_raises():
    columns = [ContextColumn(column="x", **{"from": "nope"})]
    with pytest.raises(ValueError, match="unknown context source 'nope'"):
        resolve_context(columns, {"user_id": 1})


# --- helpers ---------------------------------------------------------------

def _write(tmp_path, body):
    import textwrap
    p = tmp_path / "form.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


_LOG_FORM = """
name: log
title: Mark done
table: logs
context:
  - {column: user_id,   from: user_id}
  - {column: user_name, from: user_name}
fields:
  - key: task
    type: select
    label: What did you do?
    column: task_id
    options:
      table: tasks
      value: id
      label: title
      where: active = true
      order_by: title
  - key: done_at
    type: date
    label: When?
    default: today
  - key: comment
    type: text
    label: Any comment?
    required: false
"""
