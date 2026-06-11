"""Telegram driving adapter (aiogram). Imported lazily by the CLI so the rest
of the package works without aiogram installed."""

from .bot import run_bot

__all__ = ["run_bot"]
