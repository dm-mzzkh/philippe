"""Map a form's context columns to values from the message context.

Kept adapter-agnostic: the driving adapter builds an ``available`` dict of the
sources it can provide (``user_id``, ``user_name``, ``chat_id``, …) and this
resolves the form's declared context columns against it.
"""

from __future__ import annotations

from typing import Any

from .forms.models import ContextColumn


def resolve_context(
    columns: list[ContextColumn], available: dict[str, Any]
) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for column in columns:
        if column.source not in available:
            raise ValueError(
                f"unknown context source '{column.source}' for column "
                f"'{column.column}' (known: {', '.join(sorted(available))})"
            )
        record[column.column] = available[column.source]
    return record
