import textwrap

import pytest

from philippe.forms import FormError, load_form


def _write(tmp_path, body: str):
    p = tmp_path / "form.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


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
    assert form.fields[1].max == 5  # NumberSpec keys parsed by the field type


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
