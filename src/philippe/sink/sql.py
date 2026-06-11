"""SQL sink — INSERT a completed record as one row.

Takes an injected DB-API connection (psycopg in production, a fake in tests), so
this module never imports psycopg and stays unit-testable. Column names are
quoted identifiers; every value goes through a ``%s`` parameter — no value is
ever interpolated into the SQL text.

Each placeholder is cast to its column's actual type (``%s::task_period``,
``%s::int4``, …), discovered once per table via ``information_schema``. This is
what makes a plain Python ``str`` like ``'week'`` insert into an ENUM column:
psycopg sends ``str`` as ``text``, and there is no *implicit* text→enum cast, but
the explicit ``::task_period`` cast is valid. Other casts are harmless no-ops.
"""

from __future__ import annotations

from typing import Any

from ..db.identifiers import quote_ident
from ..forms.models import FormSpec


class SqlSink:
    def __init__(self, connection: Any) -> None:
        self._conn = connection
        self._types: dict[str, dict[str, str]] = {}  # table -> {column: udt_name}

    def save(self, form: FormSpec, record: dict[str, Any]) -> None:
        if not form.table:
            raise ValueError(f"form '{form.name}' has no 'table' to insert into")
        if not record:
            raise ValueError(f"form '{form.name}' produced an empty record")

        types = self._column_types(form.table)
        columns = list(record)
        col_sql = ", ".join(quote_ident(c) for c in columns)
        values_sql = ", ".join(_placeholder(types.get(c)) for c in columns)
        statement = (
            f"INSERT INTO {quote_ident(form.table)} ({col_sql}) VALUES ({values_sql})"
        )
        params = [record[c] for c in columns]

        try:
            with self._conn.cursor() as cur:
                cur.execute(statement, params)
            self._conn.commit()
        except Exception:
            self._conn.rollback()  # reset the aborted transaction
            raise

    def _column_types(self, table: str) -> dict[str, str]:
        """Map column → DB type name for ``table`` (cached). The type name is the
        ``information_schema`` ``udt_name`` (e.g. ``task_period``, ``int4``)."""
        if table not in self._types:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name, udt_name FROM information_schema.columns "
                    "WHERE table_name = %s",
                    [table],
                )
                self._types[table] = {name: udt for name, udt in cur.fetchall()}
        return self._types[table]


def _placeholder(udt_name: str | None) -> str:
    # udt_name comes from the pg catalog (a simple, trusted identifier).
    return f"%s::{udt_name}" if udt_name else "%s"
