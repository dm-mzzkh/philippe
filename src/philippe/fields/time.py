"""``time`` — a clock time, typed as ``HH:MM`` (e.g. a sleep start/end).

Accepts ``23:30``, ``23.30``, ``2330`` or ``7:15``; stores a real
``datetime.time`` (psycopg adapts it to a ``TIME`` column).
"""

from __future__ import annotations

import re
from datetime import time as _time

from .base import Ask, Done, FieldType, Input, InputKind, Prompt
from . import register

_PATTERN = re.compile(r"(\d{1,2})[:.\s]?(\d{2})")


def _parse(text: str) -> _time:
    m = _PATTERN.fullmatch(text.strip())
    if not m:
        raise ValueError(f"not a time: {text!r}")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"out of range: {text!r}")
    return _time(hour, minute)


@register
class Time(FieldType):
    name = "time"

    def start(self, spec, fstate):
        return Prompt(spec.label, expect={InputKind.TEXT})

    def handle(self, spec, fstate, inp):
        if inp.text:
            try:
                return Done(_parse(inp.text))
            except ValueError:
                pass
        return Ask(Prompt("Enter a time as HH:MM (e.g. 23:30).",
                          expect={InputKind.TEXT}))

    def render(self, spec, value: _time):
        return value.strftime("%H:%M")

    def to_record(self, spec, value: _time):
        return value  # a real datetime.time → psycopg adapts it to TIME
