"""Database adapters: connection, option catalog, SQL sink, and logging sink."""

from __future__ import annotations

import json
import logging
from typing import Any

from .core import FormSpec

logger = logging.getLogger("philippe.db")


def connect(dsn: str) -> Any:
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError(
            "database features need psycopg — install with `uv sync --extra bot` "
        ) from e
    return psycopg.connect(dsn, autocommit=True)


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class SqlCatalog:
    def __init__(self, connection: Any) -> None:
        self._conn = connection

    def options(self, source) -> list[tuple[str, Any]]:
        if source.query:
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

    def images(self, hashes: list[str]) -> list[tuple[bytes, str | None]]:
        """DEPRECATED — use HydrusClient.download() instead."""
        raise NotImplementedError("image storage moved to Hydrus Network")

    def query(self, sql: str) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(sql)
            columns = [c.name for c in cur.description]
            rows = cur.fetchall()
        return [dict(zip(columns, row)) for row in rows]


def _row_choice(row: dict[str, Any]) -> tuple[str, Any]:
    if "label" in row and "value" in row:
        return str(row["label"]), row["value"]
    if len(row) == 1:
        only = next(iter(row.values()))
        return str(only), only
    raise ValueError(
        "an option 'query' must return columns named 'label' and 'value' "
        "(or a single column used for both)"
    )


class SqlSink:
    def __init__(self, connection: Any) -> None:
        self._conn = connection
        self._types: dict[str, dict[str, str]] = {}

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
            self._conn.rollback()
            raise

    def exec(self, sql: str, params: list | None = None):
        """Raw UPDATE/DELETE for the hourly-check overwrite path. Returns the
        cursor so RETURNING rows can be read."""
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            row = (cur.fetchone() if cur.description else None)
        self._conn.commit()
        return row

    def insert(self, table: str, record: dict[str, Any]) -> None:
        """Same INSERT as save(), but straight into *table* (no FormSpec)."""
        if not record:
            raise ValueError("insert() got an empty record")
        types = self._column_types(table)
        columns = list(record)
        col_sql = ", ".join(quote_ident(c) for c in columns)
        values_sql = ", ".join(_placeholder(types.get(c)) for c in columns)
        statement = (
            f"INSERT INTO {quote_ident(table)} ({col_sql}) VALUES ({values_sql})"
        )
        params = [record[c] for c in columns]
        with self._conn.cursor() as cur:
            cur.execute(statement, params)
        self._conn.commit()

    def _column_types(self, table: str) -> dict[str, str]:
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
    return f"%s::{udt_name}" if udt_name else "%s"


class LoggingSink:
    def save(self, form: FormSpec, record: dict[str, Any]) -> None:
        self.insert(form.table or form.name, record)

    def insert(self, table: str, record: dict[str, Any]) -> None:
        logger.info("insert into %s: %s", table, json.dumps(record, default=str,
                                                            ensure_ascii=False))

    def exec(self, sql: str, params: list | None = None) -> None:
        logger.info("exec: %s %s", sql, params)
