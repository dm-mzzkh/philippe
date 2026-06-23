"""Typed representation of a form and its fields.

``FieldSpec`` is the base for every field type's spec; each field type may
subclass it (in ``philippe.fields.*``) to add its own YAML keys. ``FormSpec``
is a plain container holding already-validated, concrete field specs — see
:mod:`philippe.forms.loader` for how it is assembled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FieldSpec(BaseModel):
    """Keys common to every field. Subclasses add type-specific keys."""

    model_config = ConfigDict(extra="forbid")

    key: str
    type: str
    label: str
    required: bool = True
    default: Any = None
    help: str | None = None
    # DB column this field writes to (defaults to ``key``). A field type may map
    # to more than one column (e.g. ``repeat`` → period + every), in which case
    # it ignores this and names its own columns.
    column: str | None = None
    # Conditional visibility: {key: <field_key>, value: <expected_value>}.
    # Field is shown only when the named earlier field equals the given value.
    show_if: dict[str, Any] | None = None


class QueryAction(BaseModel):
    """What a `kind: query` row does when tapped: launch ``form``, pre-filling
    its fields from this row's columns (``{target_field_key: row_column}``)."""

    model_config = ConfigDict(extra="forbid")

    form: str
    prefill: dict[str, str] = {}


class ContextColumn(BaseModel):
    """A column filled from the message context (e.g. the Telegram sender),
    not asked as a field. ``source`` (YAML key ``from``) names a value the
    adapter can provide: ``user_id``, ``user_name``, or ``chat_id``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    column: str
    source: str = Field(alias="from")


@dataclass
class FormSpec:
    """A whole form. A normal form (``kind: form``) collects ``fields`` and
    writes a row; a read view (``kind: query``) runs ``query`` and lists the
    rows as buttons (no dialog, no write)."""

    name: str
    title: str
    table: str | None
    fields: list[FieldSpec]
    context: list[ContextColumn] = field(default_factory=list)
    kind: str = "form"  # "form" | "query"
    query: str | None = None
    action: QueryAction | None = None  # query rows: tap → launch a form (prefilled)
    labels: dict[str, str] = field(default_factory=dict)  # localise system strings
    submit_once: bool = False  # True → submit goes back to menu, not fill again

    def field_index(self, key: str) -> int:
        """Index of the field with ``key`` (raises ``KeyError`` if absent)."""
        for i, spec in enumerate(self.fields):
            if spec.key == key:
                return i
        raise KeyError(key)
