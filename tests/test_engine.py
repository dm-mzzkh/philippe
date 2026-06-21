import textwrap

import pytest

from philippe.dialog import Cancelled, Completed, Engine, Session, Show
from philippe.dialog.engine import BACK, CANCEL, EDIT_PREFIX, SKIP, SUBMIT
from philippe.fields.base import Input
from philippe.forms import load_form


def make_form(tmp_path, fields_yaml: str):
    p = tmp_path / "form.yaml"
    p.write_text(textwrap.dedent(f"""
        name: t
        title: T
        fields:
        {textwrap.indent(textwrap.dedent(fields_yaml), '        ')}
    """), encoding="utf-8")
    return load_form(p)


@pytest.fixture
def engine():
    return Engine()


def labels(outcome: Show):
    return [b.label for row in outcome.prompt.buttons for b in row]


def values(outcome: Show):
    return [b.value for row in outcome.prompt.buttons for b in row]


def test_happy_path_to_submit(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: name, type: title, label: Name}
        - {key: ok, type: bool, label: OK}
    """)
    s = Session(form=form)

    out = engine.start(s)
    assert isinstance(out, Show) and out.prompt.text == "Name"

    out = engine.step(s, Input(text="Alice"))
    assert out.prompt.text == "OK"  # advanced to second field

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
    engine.step(s, Input(text="first"))           # now on B
    out = engine.step(s, Input(back=True))         # back to A
    assert out.prompt.text == "A"
    assert s.cursor == 0


def test_back_on_first_field_cancels(tmp_path, engine):
    form = make_form(tmp_path, "- {key: a, type: title, label: A}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(back=True))   # nowhere back → exit the form
    assert isinstance(out, Cancelled)


def test_back_while_editing_first_field_returns_to_review(tmp_path, engine):
    form = make_form(tmp_path, """
        - {key: a, type: title, label: A}
        - {key: b, type: title, label: B}
    """)
    s = Session(form=form)
    engine.start(s)
    engine.step(s, Input(text="x"))                 # → b
    engine.step(s, Input(text="y"))                 # → review
    engine.step(s, Input(button=EDIT_PREFIX + "a"))  # edit field a (cursor 0)
    out = engine.step(s, Input(back=True))          # back → review, NOT cancel
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
    assert "at most 5" in out.prompt.text          # re-ask, not advance
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
    out = engine.step(s, Input(text="bad"))           # not a time → re-ask
    assert "HH:MM" in out.prompt.text
    out = engine.step(s, Input(text="2330"))          # 23:30 → review
    assert "review" in out.prompt.text.lower()
    done = engine.step(s, Input(button=SUBMIT))
    assert done.record == {"start_at": dt.time(23, 30)}


def test_repeat_layout_two_rows_nothing_preselected(tmp_path, engine):
    form = make_form(tmp_path, "- {key: r, type: repeat, label: R}")
    s = Session(form=form)
    out = engine.start(s)
    # period row, frequency row, then the engine's Back row
    assert len(out.prompt.buttons) == 3
    assert [b.value for b in out.prompt.buttons[0]] == ["day", "week", "month"]
    assert [b.value for b in out.prompt.buttons[1]] == ["1", "2", "3", "4"]
    assert out.prompt.buttons[1][0].label == "×1"   # ×N labels
    # nothing chosen yet → no "• " marks anywhere
    assert all(not b.label.startswith("• ")
               for row in out.prompt.buttons for b in row)


def test_repeat_needs_both_buttons_then_completes(tmp_path, engine):
    form = make_form(tmp_path, "- {key: r, type: repeat, label: R}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(button="week"))      # period only → keep waiting
    assert "review" not in out.prompt.text.lower()
    assert "• Once a week" in [b.label for b in out.prompt.buttons[0]]  # marked
    out = engine.step(s, Input(button="2"))         # frequency → both chosen → done
    assert "review" in out.prompt.text.lower()
    rec = engine.step(s, Input(button=SUBMIT))
    assert rec.record == {"period": "week", "every": 2}   # repeat → two columns


def test_repeat_order_independent_and_typed_frequency(tmp_path, engine):
    form = make_form(tmp_path, "- {key: r, type: repeat, label: R}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(text="10"))          # typed frequency first
    assert "review" not in out.prompt.text.lower()
    out = engine.step(s, Input(button="month"))     # then period → done
    assert "review" in out.prompt.text.lower()
    rec = engine.step(s, Input(button=SUBMIT))
    assert rec.record == {"period": "month", "every": 10}


def test_repeat_rejects_out_of_bounds_frequency(tmp_path, engine):
    form = make_form(tmp_path, "- {key: r, type: repeat, label: R}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(text="999"))         # invalid → re-ask, not done
    assert "1 to 365" in out.prompt.text
    assert "review" not in out.prompt.text.lower()


def test_review_buttons_show_field_and_short_answer(tmp_path, engine):
    form = make_form(tmp_path, "- {key: name, type: title, label: Name}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(text="Alice"))      # review
    edit = out.prompt.buttons[0][0]
    assert edit.label == "Name: Alice"
    assert edit.value == EDIT_PREFIX + "name"


def test_review_button_truncates_long_answer(tmp_path, engine):
    form = make_form(tmp_path, "- {key: d, type: text, label: D}")
    s = Session(form=form)
    engine.start(s)
    out = engine.step(s, Input(text="x" * 100))    # review
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
    out = engine.step(s, Input(text="y"))          # review
    assert isinstance(out, Show)

    out = engine.step(s, Input(button=EDIT_PREFIX + "a"))
    assert out.prompt.text == "A"                  # jumped to field a
    out = engine.step(s, Input(text="x2"))         # straight back to review
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
    assert out.prompt.text == "B"            # 'a' is pre-filled → asks 'b'
    assert s.answers["a"] == "preset"
    engine.step(s, Input(text="typed"))      # b → review
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
    engine.step(s, Input(text="x"))                # review
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
