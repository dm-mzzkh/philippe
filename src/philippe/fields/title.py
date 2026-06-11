"""``title`` — short single-line text. Typed, or sent as a voice message
(transcribed by the adapter when a transcriber is configured)."""

from __future__ import annotations

from .base import Ask, Done, FieldType, Input, InputKind, Prompt
from . import register


@register
class Title(FieldType):
    name = "title"

    def start(self, spec, fstate):
        return Prompt(spec.label, expect={InputKind.TEXT, InputKind.VOICE})

    def handle(self, spec, fstate, inp):
        if inp.text and inp.text.strip():
            return Done(inp.text.strip())
        return Ask(
            Prompt(
                "Please type some text (or send a voice message).",
                expect={InputKind.TEXT, InputKind.VOICE},
            )
        )
