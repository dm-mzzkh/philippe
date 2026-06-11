"""Translate an inbound aiogram message into a normalized :class:`Input`.

If a transcriber is configured, a voice message is converted to text here so
``title``/``text`` fields receive ``Input.text`` and need no special casing.
"""

from __future__ import annotations

from aiogram.types import Message

from ..fields.base import Attachment, Input, InputKind
from ..transcribe.base import Transcriber


def message_to_input(message: Message, transcriber: Transcriber | None = None) -> Input:
    if message.photo:
        return Input(attachment=Attachment(InputKind.PHOTO, message.photo[-1].file_id))
    if message.document:
        doc = message.document
        return Input(attachment=Attachment(InputKind.DOCUMENT, doc.file_id, doc.file_name))
    if message.audio:
        return Input(attachment=Attachment(InputKind.AUDIO, message.audio.file_id,
                                           message.audio.file_name))
    if message.voice:
        att = Attachment(InputKind.VOICE, message.voice.file_id)
        if transcriber is not None:
            return Input(text=transcriber.transcribe(att))
        return Input(attachment=att)
    return Input(text=message.text or "")
