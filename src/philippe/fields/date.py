"""``date`` — relative-day buttons plus typed parsing (weekday of the current
week, ``dd.mm``, or ``dd.mm.yyyy`` with ``.`` / ``/`` / space separators)."""

from __future__ import annotations

import re
from datetime import date as _date, timedelta

from .base import Ask, Button, Done, FieldType, Input, InputKind, Prompt
from . import register

_REL = [
    ("Day before yesterday", "rel:-2", -2),
    ("Yesterday", "rel:-1", -1),
    ("Today", "rel:0", 0),
    ("Tomorrow", "rel:1", 1),
]

# Maps spec.default value → the button delta that should be marked "(default)".
# Keys not present here mean "no button is highlighted" (e.g. a specific ISO date).
_DEFAULT_DELTA: dict[str | None, int] = {None: 0, "today": 0, "yesterday": -1}

_WEEKDAYS = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
}


def _parse_typed(text: str, today: _date) -> _date:
    """Parse a typed date, raising ``ValueError`` on anything unrecognized."""
    t = text.strip().lower()
    if t in _WEEKDAYS:
        return today + timedelta(days=_WEEKDAYS[t] - today.weekday())
    parts = [p for p in re.split(r"[.\s/]+", t) if p]
    if len(parts) == 2:
        day, month = int(parts[0]), int(parts[1])
        return _date(today.year, month, day)
    if len(parts) == 3:
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        if year < 100:
            year += 2000
        return _date(year, month, day)
    raise ValueError(f"unrecognized date: {text!r}")


@register
class Date(FieldType):
    name = "date"

    def _keyboard(self, spec):
        row = []
        marked = _DEFAULT_DELTA.get(spec.default)  # None → no button highlighted
        for label, value, delta in _REL:
            mark = " (default)" if marked is not None and delta == marked else ""
            row.append(Button(label + mark, value))
        return [row[:2], row[2:]]

    def start(self, spec, fstate):
        return Prompt(spec.label, self._keyboard(spec),
                      {InputKind.BUTTON, InputKind.TEXT})

    def handle(self, spec, fstate, inp):
        today = _date.today()
        if inp.button and inp.button.startswith("rel:"):
            return Done(today + timedelta(days=int(inp.button[4:])))
        if inp.text:
            try:
                return Done(_parse_typed(inp.text, today))
            except ValueError:
                pass
        return Ask(Prompt(
            "Pick a day, or type a weekday / dd.mm / dd.mm.yyyy.",
            self._keyboard(spec), {InputKind.BUTTON, InputKind.TEXT},
        ))

    def render(self, spec, value: _date):
        return value.isoformat()

    def to_record(self, spec, value: _date):
        # a real date object — psycopg adapts it to a DATE column natively;
        # LoggingSink serializes it via json default=str
        return value
