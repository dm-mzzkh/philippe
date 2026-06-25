"""Tests for core: form loader, engine, and field types."""

import textwrap

import pytest

from philippe.core import (
    BACK,
    CANCEL,
    Cancelled,
    Completed,
    EDIT_PREFIX,
    Engine,
    FormError,
    Input,
    SKIP,
    SUBMIT,
    Session,
    Show,
    load_form,
)


# --- helpers ---------------------------------------------------------------

def make_form(tmp_path, fields_yaml: str):
    p = tmp_path / "form.yaml"
    p.write_text(textwrap.dedent(f"""
        name: t
        title: T
        fields:
        {textwrap.indent(textwrap.dedent(fields_yaml), '        ')}
    """), encoding="utf-8")
    return load_form(p)


def labels(outcome: Show):
    return [b.label for row in outcome.prompt.buttons for b in row]


def values(outcome: Show):
    return [b.value for row in outcome.prompt.buttons for b in row]


# --- loader tests ----------------------------------------------------------

def test_loads_valid_form(tmp_path):
    form = load_form(_write(tmp_path, """
        name: t
        title: T
        table: tasks
        fields:
          - {key: a, type: title, label: A}
          - {key: n, type: number, label: N, min: 1, max: 5}
    """))
    assert form.name == "t"
    assert [f.key for f in form.fields] == ["a", "n"]
    assert form.fields[1].max == 5


def test_unknown_type_is_reported(tmp_path):
    with pytest.raises(FormError, match="unknown field type 'frobnicate'"):
        load_form(_write(tmp_path, """
            name: t
            title: T
            fields:
              - {key: a, type: frobnicate, label: A}
        """))


def test_duplicate_key_is_reported(tmp_path):
    with pytest.raises(FormError, match="duplicate field key 'a'"):
        load_form(_write(tmp_path, """
            name: t
            title: T
            fields:
              - {key: a, type: title, label: A}
              - {key: a, type: text, label: B}
        """))


def test_unknown_key_on_field_is_rejected(tmp_path):
    with pytest.raises(FormError):
        load_form(_write(tmp_path, """
            name: t
            title: T
            fields:
              - {key: a, type: title, label: A, bogus: 1}
        """))


def test_bad_number_range_is_rejected(tmp_path):
    with pytest.raises(FormError, match="min"):
        load_form(_write(tmp_path, """
            name: t
            title: T
            fields:
              - {key: n, type: number, label: N, min: 9, max: 1}
        """))


# --- engine tests ----------------------------------------------------------

@pytest.fixture
def engine():
    return Engine()


def test_happy_path_to_submit(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: name, type: title, label: Name}
        - {key: ok, type: bool, label: OK}
    """)
    s = Session(form=form)

    out = engine.start(s)
    assert isinstance(out, Show) and out.prompt.text == "Name"

    out = engine.step(s, Input(text="Alice"))
    assert out.prompt.text == "OK"

    out = engine.step(s, Input(button="yes"))
    assert isinstance(out, Show) and "review" in out.prompt.text.lower()

    out = engine.step(s, Input(button=SUBMIT))
    assert isinstance(out, Completed)
    assert out.record == {"name": "Alice", "ok": True}


def test_back_returns_to_previous_field(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: a, type: title, label: A}
        - {key: b, type: title, label: B}
    """)
    s = Session(form=form)
    engine.start(s)
    engine.step(s, Input(text="first"))
    out = engine.step(s, Input(back=True))
    assert out.prompt.text == "A"
    assert s.cursor == 0


def test_back_on_first_field_cancels(tmp_path, engine):
    form = make_form(tmp_path, "- {key: a, type: title, label: A}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(back=True))
    assert isinstance(out, Cancelled)


def test_back_while_editing_first_field_returns_to_review(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: a, type: title, label: A}
        - {key: b, type: title, label: B}
    """)
    s = Session(form=form)
    engine.start(s)
    engine.step(s, Input(text="x"))
    engine.step(s, Input(text="y"))
    engine.step(s, Input(button=EDIT_PREFIX + "a"))
    out = engine.step(s, Input(back=True))
    assert isinstance(out, Show) and "review" in out.prompt.text.lower()


def test_back_is_always_present(tmp_path, engine):
    form = make_form(tmp_path, "- {key: a, type: title, label: A}")
    s = Session(form=form)
    out = engine.start(s)
    assert BACK in values(out)


def test_optional_field_can_be_skipped(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: a, type: title, label: A, required: false}
        - {key: b, type: title, label: B}
    """)
    s = Session(form=form)
    out = engine.start(s)
    assert SKIP in values(out)
    out = engine.step(s, Input(button=SKIP))
    assert out.prompt.text == "B"
    assert s.answers["a"] is None


def test_number_out_of_range_reasks(tmp_path, engine):
    form = make_form(tmp_path, "- {key: n, type: number, label: N, min: 1, max: 5}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(text="9"))
    assert "at most 5" in out.prompt.text
    out = engine.step(s, Input(text="3"))
    assert isinstance(out, Show) and "review" in out.prompt.text.lower()
    assert s.answers["n"] == 3


def test_time_field_parses_and_stores_a_time(tmp_path, engine):
    import datetime as dt
    form = make_form(tmp_path, """
        - {key: start_at, type: time, label: Start}
    """)
    s = Session(form=form)
    out = engine.start(s)
    out = engine.step(s, Input(text="bad"))
    assert "HH:MM" in out.prompt.text
    out = engine.step(s, Input(text="2330"))
    assert "review" in out.prompt.text.lower()
    done = engine.step(s, Input(button=SUBMIT))
    assert done.record == {"start_at": dt.time(23, 30)}


def test_repeat_layout_two_rows_nothing_preselected(tmp_path, engine):
    form = make_form(tmp_path, "- {key: r, type: repeat, label: R}")
    s = Session(form=form)
    out = engine.start(s)
    assert len(out.prompt.buttons) == 3
    assert [b.value for b in out.prompt.buttons[0]] == ["day", "week", "month"]
    assert [b.value for b in out.prompt.buttons[1]] == ["1", "2", "3", "4"]
    assert out.prompt.buttons[1][0].label == "×1"
    assert all(not b.label.startswith("• ")
               for row in out.prompt.buttons for b in row)


def test_repeat_needs_both_buttons_then_completes(tmp_path, engine):
    form = make_form(tmp_path, "- {key: r, type: repeat, label: R}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(button="week"))
    assert "review" not in out.prompt.text.lower()
    assert "• Once a week" in [b.label for b in out.prompt.buttons[0]]
    out = engine.step(s, Input(button="2"))
    assert "review" in out.prompt.text.lower()
    rec = engine.step(s, Input(button=SUBMIT))
    assert rec.record == {"period": "week", "every": 2}


def test_repeat_order_independent_and_typed_frequency(tmp_path, engine):
    form = make_form(tmp_path, "- {key: r, type: repeat, label: R}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(text="10"))
    assert "review" not in out.prompt.text.lower()
    out = engine.step(s, Input(button="month"))
    assert "review" in out.prompt.text.lower()
    rec = engine.step(s, Input(button=SUBMIT))
    assert rec.record == {"period": "month", "every": 10}


def test_repeat_rejects_out_of_bounds_frequency(tmp_path, engine):
    form = make_form(tmp_path, "- {key: r, type: repeat, label: R}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(text="999"))
    assert "1 to 365" in out.prompt.text
    assert "review" not in out.prompt.text.lower()


def test_review_buttons_show_field_and_short_answer(tmp_path, engine):
    form = make_form(tmp_path, "- {key: name, type: title, label: Name}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(text="Alice"))
    edit = out.prompt.buttons[0][0]
    assert edit.label == "Name: Alice"
    assert edit.value == EDIT_PREFIX + "name"


def test_review_button_truncates_long_answer(tmp_path, engine):
    form = make_form(tmp_path, "- {key: d, type: text, label: D}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(text="x" * 100))
    label = out.prompt.buttons[0][0].label
    assert label.startswith("D: ") and label.endswith("…") and len(label) < 40


def test_edit_from_review_returns_to_review(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: a, type: title, label: A}
        - {key: b, type: title, label: B}
    """)
    s = Session(form=form)
    engine.start(s)
    engine.step(s, Input(text="x"))
    out = engine.step(s, Input(text="y"))
    assert isinstance(out, Show)

    out = engine.step(s, Input(button=EDIT_PREFIX + "a"))
    assert out.prompt.text == "A"
    out = engine.step(s, Input(text="x2"))
    assert "review" in out.prompt.text.lower()
    assert s.answers["a"] == "x2"

    done = engine.step(s, Input(button=SUBMIT))
    assert done.record == {"a": "x2", "b": "y"}


def test_prefill_skips_filled_fields(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: a, type: title, label: A}
        - {key: b, type: title, label: B}
    """)
    s = Session(form=form)
    out = engine.start(s, prefill={"a": "preset"})
    assert out.prompt.text == "B"
    assert s.answers["a"] == "preset"
    engine.step(s, Input(text="typed"))
    done = engine.step(s, Input(button=SUBMIT))
    assert done.record == {"a": "preset", "b": "typed"}


def test_prefill_all_fields_goes_straight_to_review(tmp_path, engine):
    form = make_form(tmp_path, "- {key: a, type: title, label: A}")
    s = Session(form=form)
    out = engine.start(s, prefill={"a": "x"})
    assert "review" in out.prompt.text.lower()


def test_cancel(tmp_path, engine):
    form = make_form(tmp_path, "- {key: a, type: title, label: A}")
    s = Session(form=form)
    engine.start(s)
    engine.step(s, Input(text="x"))
    out = engine.step(s, Input(button=CANCEL))
    assert isinstance(out, Cancelled)


def test_submit_then_restart_clears_answers(tmp_path, engine):
    form = make_form(tmp_path, "- {key: a, type: title, label: A}")
    s = Session(form=form)
    engine.start(s)
    engine.step(s, Input(text="x"))
    engine.step(s, Input(button=SUBMIT))
    out = engine.restart(s)
    assert out.prompt.text == "A"
    assert s.answers == {}


def test_back_preserves_repeat_fstate(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: r, type: repeat, label: R}
        - {key: a, type: title, label: A}
    """)
    s = Session(form=form)
    engine.start(s)
    engine.step(s, Input(button="week"))
    engine.step(s, Input(button="2"))
    engine.step(s, Input(back=True))
    assert s.fstate.get("r", {}).get("period") == "week"
    assert s.fstate.get("r", {}).get("every") == 2


def test_custom_labels_appear_in_buttons(tmp_path, engine):
    p = tmp_path / "form.yaml"
    p.write_text(textwrap.dedent("""
        name: t
        title: T
        labels:
          back: "◀ Назад"
          skip: "Пропустить"
          cancel: "✖ Отмена"
          submit: "✔ Сохранить"
          review_prompt: "Проверь ответы:"
        fields:
          - key: a
            type: title
            label: A
            required: false
    """), encoding="utf-8")
    form = load_form(p)
    s = Session(form=form)
    out = engine.start(s)
    btn_labels = labels(out)
    assert "Пропустить" in btn_labels
    assert "◀ Назад" in btn_labels

    engine.start(s)  # reset
    out = engine.step(s, Input(text="x"))
    assert "Проверь ответы:" in out.prompt.text
    btn_labels = labels(out)
    assert "✖ Отмена" in btn_labels
    assert "✔ Сохранить" in btn_labels


def test_submit_once_completed_has_restart_false(tmp_path, engine):
    p = tmp_path / "form.yaml"
    p.write_text(textwrap.dedent("""
        name: t
        title: T
        submit_once: true
        fields:
          - {key: a, type: title, label: A}
    """), encoding="utf-8")
    form = load_form(p)
    s = Session(form=form)
    engine.start(s)
    engine.step(s, Input(text="x"))
    done = engine.step(s, Input(button=SUBMIT))
    assert isinstance(done, Completed)
    assert done.restart is False


def test_default_form_completed_has_restart_true(tmp_path, engine):
    form = make_form(tmp_path, "- {key: a, type: title, label: A}")
    s = Session(form=form)
    engine.start(s)
    engine.step(s, Input(text="x"))
    done = engine.step(s, Input(button=SUBMIT))
    assert done.restart is True


def test_show_if_hides_field_when_condition_unmet(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: type, type: title, label: Type}
        - key: extra
          type: title
          label: Extra
          show_if: {key: type, value: "special"}
        - {key: name, type: title, label: Name}
    """)
    s = Session(form=form)
    engine.start(s)
    engine.step(s, Input(text="normal"))
    out = engine.step(s, Input(text="x"))
    assert "review" in out.prompt.text.lower()
    done = engine.step(s, Input(button=SUBMIT))
    assert "extra" not in done.record


def test_show_if_shows_field_when_condition_met(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: type, type: title, label: Type}
        - key: extra
          type: title
          label: Extra
          show_if: {key: type, value: "special"}
        - {key: name, type: title, label: Name}
    """)
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(text="special"))
    assert out.prompt.text == "Extra"
    engine.step(s, Input(text="bonus"))
    engine.step(s, Input(text="Alice"))
    done = engine.step(s, Input(button=SUBMIT))
    assert done.record["extra"] == "bonus"
    assert done.record["name"] == "Alice"


# --- helpers ---------------------------------------------------------------

def _write(tmp_path, body: str):
    p = tmp_path / "form.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p