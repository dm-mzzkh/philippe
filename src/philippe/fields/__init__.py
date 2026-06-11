"""The field-type catalogue and its registry.

Adding a field type = add a module here, subclass :class:`FieldType`, and apply
``@register``. The loader and dialog engine discover it through this registry —
nothing else changes.
"""

from __future__ import annotations

from .base import (
    Ask,
    Attachment,
    Button,
    Done,
    FieldType,
    Input,
    InputKind,
    Prompt,
    Step,
)

_REGISTRY: dict[str, FieldType] = {}


class FieldTypeNotFound(Exception):
    """Raised when a ``type:`` in a form has no registered handler."""


def register(cls: type[FieldType]) -> type[FieldType]:
    """Class decorator: instantiate the field type and add it to the registry."""
    instance = cls()
    if not getattr(instance, "name", None):
        raise ValueError(f"{cls.__name__} must define a non-empty 'name'")
    if instance.name in _REGISTRY:
        raise ValueError(f"duplicate field type '{instance.name}'")
    _REGISTRY[instance.name] = instance
    return cls


def get_field_type(name: str) -> FieldType:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise FieldTypeNotFound(
            f"unknown field type '{name}' (known: {', '.join(sorted(_REGISTRY))})"
        ) from None


def all_field_types() -> dict[str, FieldType]:
    return dict(_REGISTRY)


# Import the type modules so their @register decorators run and populate the
# registry. Kept at the bottom to avoid a circular import with .base.
from . import (  # noqa: E402,F401
    attachment,
    boolean,
    date,
    number,
    repeat,
    select,
    text,
    title,
)

__all__ = [
    "Ask",
    "Attachment",
    "Button",
    "Done",
    "FieldType",
    "FieldTypeNotFound",
    "Input",
    "InputKind",
    "Prompt",
    "Step",
    "all_field_types",
    "get_field_type",
    "register",
]
