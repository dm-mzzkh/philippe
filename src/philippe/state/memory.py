"""In-memory session store (MVP). Sessions are lost on restart; swap in a
Redis/SQL impl behind :class:`SessionStore` to persist them."""

from __future__ import annotations

from ..dialog.session import Session


class MemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[int, Session] = {}

    def get(self, chat_id: int) -> Session | None:
        return self._sessions.get(chat_id)

    def put(self, chat_id: int, session: Session) -> None:
        self._sessions[chat_id] = session

    def drop(self, chat_id: int) -> None:
        self._sessions.pop(chat_id, None)
