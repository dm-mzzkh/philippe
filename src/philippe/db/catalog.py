"""The option catalog — supplies a dynamic ``select``'s choices from the DB."""

from __future__ import annotations

from typing import Any, Protocol

from ..fields.select import OptionSource
from .identifiers import quote_ident


class Catalog(Protocol):
    def options(self, source: OptionSource) -> list[tuple[str, Any]]:
        """Return ``(label, value)`` pairs for a select's dynamic source."""
        ...

    def query(self, sql: str) -> list[dict[str, Any]]:
        """Run a read-only SQL query (from a `kind: query` form) → list of rows
        as ``{column: value}`` dicts."""
        ...


class SqlCatalog:
    """Reads options from SQL via an injected DB-API connection."""

    def __init__(self, connection: Any) -> None:
        self._conn = connection

    def options(self, source: OptionSource) -> list[tuple[str, Any]]:
        if source.query:  # raw SQL from the trusted form file
            return [_row_choice(row) for row in self.query(source.query)]

        query = (
            f"SELECT {quote_ident(source.label)} AS label, "
            f"{quote_ident(source.value)} AS value "
            f"FROM {quote_ident(source.table)}"
        )
        if source.where:
            query += f" WHERE {source.where}"
        if source.order_by:
            query += f" ORDER BY {source.order_by}"
        with self._conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return [(str(label), value) for label, value in rows]

    def query(self, sql: str) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(sql)
            columns = [c.name for c in cur.description]
            rows = cur.fetchall()
        return [dict(zip(columns, row)) for row in rows]


def _row_choice(row: dict[str, Any]) -> tuple[str, Any]:
    """Extract a (label, value) pair from a raw option-query row."""
    if "label" in row and "value" in row:
        return str(row["label"]), row["value"]
    if len(row) == 1:  # one column → use it for both
        only = next(iter(row.values()))
        return str(only), only
    raise ValueError(
        "an option 'query' must return columns named 'label' and 'value' "
        "(or a single column used for both)"
    )
