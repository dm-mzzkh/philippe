"""The session-storage port. Adapters depend on this Protocol, not an impl."""

from __future__ import annotations

from typing import Protocol

from ..dialog.session import Session


class SessionStore(Protocol):
    def get(self, chat_id: int) -> Session | None: ...

    def put(self, chat_id: int, session: Session) -> None: ...

    def drop(self, chat_id: int) -> None: ...
