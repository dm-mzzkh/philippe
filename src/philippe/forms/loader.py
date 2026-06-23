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
from .models import ContextColumn, FieldSpec, FormSpec, QueryAction


class _Envelope(BaseModel):
    """The top-level form keys; ``fields`` stays raw for per-type validation."""

    model_config = ConfigDict(extra="forbid")

    name: str
    title: str
    table: str | None = None
    kind: str = "form"
    query: str | None = None
    action: QueryAction | None = None
    context: list[ContextColumn] = []
    fields: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    submit_once: bool = False


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

    if envelope.kind == "query":
        if not (envelope.query and envelope.query.strip()):
            raise FormError(f"{path}: a 'query' form needs a non-empty 'query'")
        fields: list[FieldSpec] = []
    elif envelope.kind == "form":
        if envelope.action is not None:
            raise FormError(f"{path}: 'action' is only for kind: query forms")
        fields = _load_fields(path, envelope.fields)
    else:
        raise FormError(f"{path}: unknown kind '{envelope.kind}' (form | query)")

    return FormSpec(
        name=envelope.name,
        title=envelope.title,
        table=envelope.table,
        fields=fields,
        context=list(envelope.context),
        kind=envelope.kind,
        query=envelope.query,
        action=envelope.action,
        labels=dict(envelope.labels),
        submit_once=envelope.submit_once,
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
    errors = e.errors()
    # In a union (e.g. options: list | OptionSource) one branch reports a generic
    # "wrong shape" error; prefer a validator (value_error) message — it's the
    # actionable one.
    err = next((x for x in errors if x["type"] == "value_error"), errors[0])
    # Drop union-branch / function-wrapper noise from the location path.
    parts = [str(p) for p in err["loc"] if "[" not in str(p)]
    loc = ".".join(parts) or "(root)"
    msg = err["msg"].removeprefix("Value error, ")
    return f"{loc}: {msg}"
