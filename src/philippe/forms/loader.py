"""Read a ``form.yaml`` file into a validated :class:`FormSpec`.

Each raw field is dispatched to its field type's spec model via the field
registry, so type-specific keys (``min``/``options``/…) are validated by the
type that owns them. Every failure becomes a :class:`FormError` with context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .errors import FormError
from .models import FieldSpec, FormSpec


class _Envelope(BaseModel):
    """The top-level form keys; ``fields`` stays raw for per-type validation."""

    model_config = ConfigDict(extra="forbid")

    name: str
    title: str
    table: str | None = None
    fields: list[dict[str, Any]]


def load_form(path: str | Path) -> FormSpec:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise FormError(f"Form file not found: {path}") from e
    except OSError as e:
        raise FormError(f"Could not read {path}: {e}") from e
    except yaml.YAMLError as e:
        raise FormError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(raw, dict):
        raise FormError(f"{path}: the top level must be a mapping")

    try:
        envelope = _Envelope.model_validate(raw)
    except ValidationError as e:
        raise FormError(f"{path}: {_first_error(e)}") from e

    fields = _load_fields(path, envelope.fields)
    return FormSpec(
        name=envelope.name,
        title=envelope.title,
        table=envelope.table,
        fields=fields,
    )


def _load_fields(path: Path, raw_fields: list[dict[str, Any]]) -> list[FieldSpec]:
    # Imported lazily: fields.base depends on forms.models, so importing the
    # registry at module scope would form an import cycle.
    from ..fields import FieldTypeNotFound, get_field_type

    if not raw_fields:
        raise FormError(f"{path}: the form has no fields")

    specs: list[FieldSpec] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_fields):
        if not isinstance(raw, dict):
            raise FormError(f"{path}: field #{i} must be a mapping")
        key = raw.get("key", f"#{i}")
        ftype = raw.get("type")
        if not ftype:
            raise FormError(f"{path}: field '{key}' is missing 'type'")
        try:
            field_type = get_field_type(ftype)
        except FieldTypeNotFound as e:
            raise FormError(f"{path}: field '{key}': {e}") from e
        try:
            spec = field_type.spec_model.model_validate(raw)
        except ValidationError as e:
            raise FormError(
                f"{path}: field '{key}' (type {ftype}): {_first_error(e)}"
            ) from e
        if spec.key in seen:
            raise FormError(f"{path}: duplicate field key '{spec.key}'")
        seen.add(spec.key)
        specs.append(spec)
    return specs


def _first_error(e: ValidationError) -> str:
    err = e.errors()[0]
    loc = ".".join(str(p) for p in err["loc"]) or "(root)"
    return f"{loc}: {err['msg']}"
