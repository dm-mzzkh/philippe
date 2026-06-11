"""Safe SQL identifier quoting.

Table and column names come from the form file (a trusted author), but we still
quote them so names that need it work and accidental injection via a stray name
is impossible. Values are never interpolated — they go through parameters.
"""

from __future__ import annotations


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
