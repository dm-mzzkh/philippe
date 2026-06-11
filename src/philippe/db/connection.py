"""Open a database connection. The only place psycopg is imported."""

from __future__ import annotations

from typing import Any


def connect(dsn: str) -> Any:
    """Return a psycopg connection for ``dsn`` (e.g.
    ``postgresql://bot:bot@localhost:5432/bot_dev``)."""
    try:
        import psycopg
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "database features need psycopg — install with `uv sync --extra db`"
        ) from e
    # autocommit: each INSERT is its own row, and option SELECTs at /start don't
    # leave an idle-in-transaction snapshot open between dialogs.
    return psycopg.connect(dsn, autocommit=True)
