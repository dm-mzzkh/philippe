"""The option catalog — supplies a dynamic ``select``'s choices from the DB."""

from __future__ import annotations

from typing import Any, Protocol

from ..fields.select import OptionSource
from .identifiers import quote_ident


class Catalog(Protocol):
    def options(self, source: OptionSource) -> list[tuple[str, Any]]:
        """Return ``(label, value)`` pairs for a select's dynamic source."""
        ...


class SqlCatalog:
    """Reads options from SQL via an injected DB-API connection."""

    def __init__(self, connection: Any) -> None:
        self._conn = connection

    def options(self, source: OptionSource) -> list[tuple[str, Any]]:
        query = (
            f"SELECT {quote_ident(source.label)} AS label, "
            f"{quote_ident(source.value)} AS value "
            f"FROM {quote_ident(source.table)}"
        )
        if source.where:  # raw SQL from the trusted form file
            query += f" WHERE {source.where}"
        if source.order_by:
            query += f" ORDER BY {source.order_by}"
        with self._conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return [(str(label), value) for label, value in rows]
