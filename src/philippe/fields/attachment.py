"""``photo`` / ``media`` / ``audio`` — the user sends the matching attachment.

In the MVP the stored value is the Telegram ``file_id`` (the bot keeps a
reference, not the bytes). All three share one implementation parameterized by
the kind of attachment they accept.
"""

from __future__ import annotations

from typing import ClassVar

from .base import Ask, Attachment, Done, FieldType, Input, InputKind, Prompt
from . import register


class _AttachmentField(FieldType):
    accept: ClassVar[InputKind]
    noun: ClassVar[str]

    def start(self, spec, fstate):
        return Prompt(spec.label, expect={self.accept})

    def handle(self, spec, fstate, inp):
        att = inp.attachment
        if att is not None and att.kind == self.accept:
            return Done(att)
        return Ask(Prompt(f"Please send {self.noun}.", expect={self.accept}))

    def render(self, spec, value: Attachment):
        return f"<{self.noun}: {value.file_name or value.file_id}>"

    def to_record(self, spec, value: Attachment):
        return value.file_id


@register
class Photo(_AttachmentField):
    name = "photo"
    accept = InputKind.PHOTO
    noun = "a photo"


@register
class Media(_AttachmentField):
    name = "media"
    accept = InputKind.DOCUMENT
    noun = "a file"


@register
class Audio(_AttachmentField):
    name = "audio"
    accept = InputKind.AUDIO
    noun = "an audio message"
