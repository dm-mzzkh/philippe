"""The transcription port. A driving adapter, if given a ``Transcriber``,
converts a voice attachment into ``Input.text`` before it reaches a field, so
``title``/``text`` field types stay unchanged whether or not voice is enabled.
"""

from __future__ import annotations

from typing import Protocol

from ..fields.base import Attachment


class Transcriber(Protocol):
    def transcribe(self, audio: Attachment) -> str: ...
