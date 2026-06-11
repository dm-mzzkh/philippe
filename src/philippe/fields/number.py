"""``number`` — a numeric value with ``[min, max]`` validation and optional
preset buttons."""

from __future__ import annotations

from pydantic import model_validator

from ..forms.models import FieldSpec
from .base import Ask, Button, Done, FieldType, Input, InputKind, Prompt
from . import register


class NumberSpec(FieldSpec):
    min: float | None = None
    max: float | None = None
    presets: list[float] | None = None

    @model_validator(mode="after")
    def _check_range(self) -> "NumberSpec":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("'min' must be <= 'max'")
        return self


def _fmt(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def _coerce(raw: str):
    return float(raw.replace(",", ".").strip())


@register
class Number(FieldType):
    name = "number"
    spec_model = NumberSpec

    def _keyboard(self, spec: NumberSpec):
        if not spec.presets:
            return []
        return [[Button(_fmt(p), _fmt(p)) for p in spec.presets]]

    def _hint(self, spec: NumberSpec) -> str:
        if spec.min is not None and spec.max is not None:
            return f"{spec.label} ({_fmt(spec.min)}–{_fmt(spec.max)})"
        if spec.min is not None:
            return f"{spec.label} (≥ {_fmt(spec.min)})"
        if spec.max is not None:
            return f"{spec.label} (≤ {_fmt(spec.max)})"
        return spec.label

    def start(self, spec, fstate):
        return Prompt(
            self._hint(spec), self._keyboard(spec), {InputKind.TEXT, InputKind.BUTTON}
        )

    def handle(self, spec, fstate, inp):
        raw = inp.button if inp.button is not None else inp.text
        try:
            value = _coerce(raw or "")
        except (TypeError, ValueError):
            return Ask(Prompt("Please enter a number.", self._keyboard(spec),
                              {InputKind.TEXT, InputKind.BUTTON}))
        if value.is_integer():
            value = int(value)
        if spec.min is not None and value < spec.min:
            return Ask(Prompt(f"Must be at least {_fmt(spec.min)}.", self._keyboard(spec),
                              {InputKind.TEXT, InputKind.BUTTON}))
        if spec.max is not None and value > spec.max:
            return Ask(Prompt(f"Must be at most {_fmt(spec.max)}.", self._keyboard(spec),
                              {InputKind.TEXT, InputKind.BUTTON}))
        return Done(value)

    def render(self, spec, value):
        return _fmt(value)
