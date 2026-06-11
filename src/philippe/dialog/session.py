"""Per-conversation state. Holds everything needed to resume a half-filled form
for one chat; deliberately a plain dataclass so any ``SessionStore`` can keep it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..forms.models import FormSpec


@dataclass
class Session:
    form: FormSpec
    answers: dict[str, Any] = field(default_factory=dict)
    cursor: int = 0
    fstate: dict[str, dict] = field(default_factory=dict)
    mode: str = "filling"  # "filling" | "review"
    return_to_review: bool = False

    @property
    def current(self):
        return self.form.fields[self.cursor]
