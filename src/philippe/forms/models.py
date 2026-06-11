"""Typed representation of a form and its fields.

``FieldSpec`` is the base for every field type's spec; each field type may
subclass it (in ``philippe.fields.*``) to add its own YAML keys. ``FormSpec``
is a plain container holding already-validated, concrete field specs — see
:mod:`philippe.forms.loader` for how it is assembled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict


class FieldSpec(BaseModel):
    """Keys common to every field. Subclasses add type-specific keys."""

    model_config = ConfigDict(extra="forbid")

    key: str
    type: str
    label: str
    required: bool = True
    default: Any = None
    help: str | None = None


@dataclass
class FormSpec:
    """A whole form: metadata plus an ordered list of concrete field specs."""

    name: str
    title: str
    table: str | None
    fields: list[FieldSpec]

    def field_index(self, key: str) -> int:
        """Index of the field with ``key`` (raises ``KeyError`` if absent)."""
        for i, spec in enumerate(self.fields):
            if spec.key == key:
                return i
        raise KeyError(key)
