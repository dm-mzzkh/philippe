"""``repeat`` — a recurrence rule shown as a single message with two button rows:
the period (``Every day`` / ``Once a week`` / ``Once a month``) and the
multiplier (``×1``…``×4``).

The user taps one button from each row; the chosen button is marked ``• `` and
the field completes once **both** a period and a frequency have been picked. The
frequency can also be typed (1–365). The Telegram adapter edits the message in
place on each tap, so nothing is re-sent — the same message just updates.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..forms.models import FieldSpec
from .base import Ask, Button, Done, FieldType, Input, InputKind, Prompt
from . import register


class RepeatSpec(FieldSpec):
    # repeat fills two columns; name them here (defaults match the home_cal schema)
    period_column: str = "period"
    every_column: str = "every"


_PERIODS = [("Every day", "day"), ("Once a week", "week"), ("Once a month", "month")]
_PERIOD_VALUES = {value for _, value in _PERIODS}
_FREQ_BUTTONS = [1, 2, 3, 4]
_UNIT = {"day": "day", "week": "week", "month": "month"}


@dataclass
class Recurrence:
    period: str  # "day" | "week" | "month"
    frequency: int


def _mark(label: str, selected: bool) -> str:
    return f"• {label}" if selected else label


@register
class Repeat(FieldType):
    name = "repeat"
    spec_model = RepeatSpec

    def _prompt(self, fstate: dict, hint: str | None = None) -> Prompt:
        period = fstate.get("period")
        every = fstate.get("every")
        period_row = [
            Button(_mark(label, value == period), value) for label, value in _PERIODS
        ]
        freq_row = [
            Button(_mark(f"×{n}", n == every), str(n)) for n in _FREQ_BUTTONS
        ]
        text = hint or "How often does it repeat? Pick a period and ×N:"
        return Prompt(text, [period_row, freq_row], {InputKind.BUTTON, InputKind.TEXT})

    def start(self, spec, fstate):
        return self._prompt(fstate)

    def handle(self, spec, fstate, inp):
        token = (inp.button if inp.button is not None else inp.text or "").strip()

        if token in _PERIOD_VALUES:
            fstate["period"] = token
        else:
            try:
                every = int(token)
            except ValueError:
                every = 0
            if 1 <= every <= 365:
                fstate["every"] = every
            else:
                return Ask(self._prompt(
                    fstate, "Pick a period and ×N, or type a number from 1 to 365."
                ))

        if "period" in fstate and "every" in fstate:
            return Done(Recurrence(fstate["period"], fstate["every"]))
        return Ask(self._prompt(fstate))  # one dimension still missing — keep waiting

    def render(self, spec, value: Recurrence):
        unit = _UNIT[value.period]
        if value.frequency == 1:
            return f"every {unit}"
        return f"every {value.frequency} {unit}s"

    def to_record(self, spec, value: Recurrence):
        return {"period": value.period, "frequency": value.frequency}

    def columns(self, spec: RepeatSpec):
        return [spec.period_column, spec.every_column]

    def to_columns(self, spec: RepeatSpec, value: Recurrence):
        return {spec.period_column: value.period, spec.every_column: value.frequency}
