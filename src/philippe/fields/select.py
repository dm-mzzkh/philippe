"""``select`` — pick one option from a fixed set, optionally allowing a typed
custom value.

Options are either a **static list** of strings, or a **dynamic source** read
from the database (``{table, value, label, where, order_by}``). A dynamic
source is materialized once per dialog into ``(label, value)`` choices: the
button shows ``label`` while the field stores the typed ``value`` (e.g. show a
task title, store its id). See :func:`philippe.db.resolve.resolve_form`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, PrivateAttr, model_validator

from ..forms.models import FieldSpec
from .base import Ask, Button, Done, FieldType, Input, InputKind, Prompt
from . import register


class OptionSource(BaseModel):
    """Where a select's options come from at dialog start.

    Two forms (mutually exclusive):

    * structured — ``{table, value, label, where?, order_by?}``: the common case,
      builds ``SELECT label, value FROM table [WHERE …] [ORDER BY …]``.
    * raw ``query`` — any SQL you like; it must return columns named ``label`` and
      ``value`` (or a single column, used for both). Use this for ``DISTINCT``,
      joins, aggregates, etc.
    """

    model_config = ConfigDict(extra="forbid")

    table: str | None = None
    value: str | None = None
    label: str | None = None
    where: str | None = None
    order_by: str | None = None
    query: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "OptionSource":
        structured = ("table", "value", "label", "where", "order_by")
        if self.query:
            used = [k for k in structured if getattr(self, k)]
            if used:
                raise ValueError(f"'query' cannot be combined with {used}")
        else:
            missing = [k for k in ("table", "value", "label") if not getattr(self, k)]
            if missing:
                raise ValueError(
                    f"option source needs {missing} (or a raw 'query' instead)"
                )
        return self


class SelectSpec(FieldSpec):
    options: list[str] | OptionSource
    allow_custom: bool = False

    # Materialized (label, value) pairs. For a static list this stays None and
    # is derived on the fly; for an OptionSource the resolver fills it per dialog.
    _choices: list[tuple[str, Any]] | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _check(self) -> "SelectSpec":
        if isinstance(self.options, list):
            if not self.options:
                raise ValueError("'options' must list at least one choice")
            if self.default is not None and self.default not in self.options:
                raise ValueError(f"'default' {self.default!r} is not one of options")
        return self

    @property
    def is_dynamic(self) -> bool:
        return isinstance(self.options, OptionSource)

    def choices(self) -> list[tuple[str, Any]]:
        """The (label, value) pairs to offer. Raises if a dynamic source was
        never resolved."""
        if self._choices is not None:
            return self._choices
        if isinstance(self.options, list):
            return [(opt, opt) for opt in self.options]
        raise RuntimeError(
            f"select '{self.key}' has dynamic options that were not resolved"
        )

    def set_choices(self, choices: list[tuple[str, Any]]) -> None:
        self._choices = list(choices)


@register
class Select(FieldType):
    name = "select"
    spec_model = SelectSpec

    def _keyboard(self, spec: SelectSpec):
        rows = []
        for label, value in spec.choices():
            shown = f"{label} (default)" if value == spec.default else label
            rows.append([Button(shown, str(value))])
        return rows

    def _expect(self, spec: SelectSpec):
        kinds = {InputKind.BUTTON}
        if spec.allow_custom:
            kinds.add(InputKind.TEXT)
        return kinds

    def start(self, spec, fstate):
        return Prompt(spec.label, self._keyboard(spec), self._expect(spec))

    def handle(self, spec, fstate, inp):
        if inp.button is not None:
            for _, value in spec.choices():
                if str(value) == inp.button:
                    return Done(value)
        if spec.allow_custom and inp.text and inp.text.strip():
            return Done(inp.text.strip())
        msg = "Please pick one of the options."
        if spec.allow_custom:
            msg = "Pick an option, or type your own value."
        return Ask(Prompt(msg, self._keyboard(spec), self._expect(spec)))

    def render(self, spec, value):
        for label, choice_value in spec.choices():
            if choice_value == value:
                return label
        return str(value)
