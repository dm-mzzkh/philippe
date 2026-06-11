"""``bool`` — a yes/no answer rendered as two buttons."""

from __future__ import annotations

from .base import Ask, Button, Done, FieldType, Input, InputKind, Prompt
from . import register

_YES = {"yes", "y", "да", "true", "1"}
_NO = {"no", "n", "нет", "false", "0"}


@register
class Boolean(FieldType):
    name = "bool"

    def _keyboard(self, spec):
        yes, no = "Yes", "No"
        if spec.default is True:
            yes = "Yes (default)"
        elif spec.default is False:
            no = "No (default)"
        return [[Button(yes, "yes"), Button(no, "no")]]

    def start(self, spec, fstate):
        return Prompt(spec.label, self._keyboard(spec),
                      {InputKind.BUTTON, InputKind.TEXT})

    def handle(self, spec, fstate, inp):
        token = (inp.button or inp.text or "").strip().lower()
        if token in _YES:
            return Done(True)
        if token in _NO:
            return Done(False)
        return Ask(Prompt("Please tap Yes or No.", self._keyboard(spec),
                          {InputKind.BUTTON, InputKind.TEXT}))

    def render(self, spec, value):
        return "Yes" if value else "No"
