"""The record-sink port. The MVP echoes records; a SQL impl writes rows."""

from __future__ import annotations

from typing import Any, Protocol

from ..forms.models import FormSpec


class RecordSink(Protocol):
    def save(self, form: FormSpec, record: dict[str, Any]) -> None: ...
