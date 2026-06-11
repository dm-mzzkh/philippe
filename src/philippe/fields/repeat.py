"""``repeat`` — a recurrence rule asked in two steps: period, then frequency.

This is the canonical multi-step field: it remembers which sub-step it is on in
``fstate`` so the engine doesn't need to know about its internal flow.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Ask, Button, Done, FieldType, Input, InputKind, Prompt
from . import register

_PERIODS = [
    ("Every day", "day"),
    ("Once a week (default)", "week"),
    ("Once a month", "month"),
]
_PERIOD_VALUES = {v for _, v in _PERIODS}
_UNIT = {"day": "day", "week": "week", "month": "month"}


@dataclass
class Recurrence:
    period: str  # "day" | "week" | "month"
    frequency: int


def _period_keyboard():
    return [[Button(label, value)] for label, value in _PERIODS]


def _freq_keyboard():
    return [[Button("1 (default)", "1"), Button("2", "2"),
             Button("3", "3"), Button("4", "4")]]


@register
class Repeat(FieldType):
    name = "repeat"

    def start(self, spec, fstate):
        fstate["step"] = "period"
        return Prompt("How often? Pick a period:", _period_keyboard(),
                      {InputKind.BUTTON})

    def handle(self, spec, fstate, inp):
        if fstate.get("step") != "frequency":
            if inp.button in _PERIOD_VALUES:
                fstate["period"] = inp.button
                fstate["step"] = "frequency"
                return Ask(Prompt("Every how many?", _freq_keyboard(),
                                  {InputKind.BUTTON, InputKind.TEXT}))
            return Ask(Prompt("Pick a period.", _period_keyboard(),
                              {InputKind.BUTTON}))

        raw = inp.button if inp.button is not None else inp.text
        try:
            freq = int((raw or "").strip())
        except (TypeError, ValueError):
            freq = 0
        if not 1 <= freq <= 365:
            return Ask(Prompt("Enter a whole number from 1 to 365.",
                              _freq_keyboard(), {InputKind.BUTTON, InputKind.TEXT}))
        return Done(Recurrence(fstate["period"], freq))

    def render(self, spec, value: Recurrence):
        unit = _UNIT[value.period]
        if value.frequency == 1:
            return f"every {unit}"
        return f"every {value.frequency} {unit}s"

    def to_record(self, spec, value: Recurrence):
        return {"period": value.period, "frequency": value.frequency}
