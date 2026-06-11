"""Telegram driving adapter (aiogram). Imported lazily by the CLI so the core
and the console driver work without aiogram installed."""

from .bot import run_bot

__all__ = ["run_bot"]
