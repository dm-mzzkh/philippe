"""Database access: connection, the option catalog, and form resolution.

Only :mod:`philippe.db.connection` imports psycopg, and it does so lazily — the
catalog, resolver, and SQL sink operate on an injected DB-API connection, so
they are unit-testable with a fake connection and import fine without psycopg.
"""

from .catalog import Catalog, SqlCatalog
from .resolve import form_needs_db, resolve_form

__all__ = ["Catalog", "SqlCatalog", "form_needs_db", "resolve_form"]
