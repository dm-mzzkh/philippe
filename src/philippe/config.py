"""Runtime settings, assembled from CLI args and environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

TOKEN_ENV = "PHILIPPE_BOT_TOKEN"
DATABASE_ENV = "DATABASE_URL"
ALLOWED_ENV = "PHILIPPE_ALLOWED_IDS"  # comma-separated Telegram user ids


def load_env(path: str | Path | None = None) -> None:
    """Load variables from a ``.env`` file into the environment.

    Existing environment variables win over ``.env`` (so an explicit
    ``PHILIPPE_BOT_TOKEN=… uv run …`` overrides the file). No-op if the file is
    missing, or if ``python-dotenv`` is not installed.
    """
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    dotenv_path = str(path) if path else find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)


@dataclass
class Settings:
    form_path: Path
    token: str | None = None
    log_level: str = "INFO"


def resolve_token(explicit: str | None) -> str:
    token = explicit or os.environ.get(TOKEN_ENV)
    if not token:
        raise SystemExit(
            f"No bot token. Pass --token or set {TOKEN_ENV} in the environment."
        )
    return token


def resolve_database_url(explicit: str | None) -> str | None:
    """The DB DSN if configured (flag or env), else None (→ logging sink)."""
    return explicit or os.environ.get(DATABASE_ENV)


def resolve_allowed_ids(explicit: str | None) -> set[int] | None:
    """Whitelist of Telegram user ids that may use the bot (flag or env). None →
    open to everyone. Raises SystemExit on a malformed list."""
    raw = explicit or os.environ.get(ALLOWED_ENV)
    if not raw:
        return None
    try:
        return {int(part) for part in raw.replace(" ", "").split(",") if part}
    except ValueError:
        raise SystemExit(f"{ALLOWED_ENV} must be comma-separated ids, e.g. 111,222")
