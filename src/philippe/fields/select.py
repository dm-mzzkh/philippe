"""``select`` — pick one option from a fixed set, optionally allowing a typed
custom value."""

from __future__ import annotations

from pydantic import model_validator

from ..forms.models import FieldSpec
from .base import Ask, Button, Done, FieldType, Input, InputKind, Prompt
from . import register


class SelectSpec(FieldSpec):
    options: list[str]
    allow_custom: bool = False

    @model_validator(mode="after")
    def _check(self) -> "SelectSpec":
        if not self.options:
            raise ValueError("'options' must list at least one choice")
        if self.default is not None and self.default not in self.options:
            raise ValueError(f"'default' {self.default!r} is not one of options")
        return self


@register
class Select(FieldType):
    name = "select"
    spec_model = SelectSpec

    def _keyboard(self, spec: SelectSpec):
        rows = []
        for opt in spec.options:
            label = f"{opt} (default)" if opt == spec.default else opt
            rows.append([Button(label, opt)])
        return rows

    def _expect(self, spec: SelectSpec):
        kinds = {InputKind.BUTTON}
        if spec.allow_custom:
            kinds.add(InputKind.TEXT)
        return kinds

    def start(self, spec, fstate):
        return Prompt(spec.label, self._keyboard(spec), self._expect(spec))

    def handle(self, spec, fstate, inp):
        if inp.button in spec.options:
            return Done(inp.button)
        if spec.allow_custom and inp.text and inp.text.strip():
            return Done(inp.text.strip())
        msg = "Please pick one of the options."
        if spec.allow_custom:
            msg = "Pick an option, or type your own value."
        return Ask(Prompt(msg, self._keyboard(spec), self._expect(spec)))
