"""Compose the Telegram adapter and start long-polling."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import BotCommand

from ..forms.models import FormSpec
from ..sink import LoggingSink
from ..sink.base import RecordSink
from ..state import MemorySessionStore
from ..state.store import SessionStore
from .handlers import Runner, build_dispatcher

logger = logging.getLogger("philippe.telegram")


def run_bot(
    forms: dict[str, FormSpec],
    token: str,
    sink: RecordSink | None = None,
    store: SessionStore | None = None,
    catalog=None,
    allowed_ids: set[int] | None = None,
) -> None:
    runner = Runner(
        forms, sink or LoggingSink(), store or MemorySessionStore(), catalog=catalog
    )
    dispatcher = build_dispatcher(runner, allowed_ids=allowed_ids)
    bot = Bot(token)

    async def _main() -> None:
        logger.info("starting bot with forms: %s%s", ", ".join(forms),
                    f" (whitelist: {len(allowed_ids)} ids)" if allowed_ids else "")
        try:
            await bot.set_my_commands([
                BotCommand(command="forms", description="List forms to fill"),
                BotCommand(command="start", description="List forms to fill"),
            ])
            await bot.delete_webhook(drop_pending_updates=True)
            await dispatcher.start_polling(bot)
        finally:
            await bot.session.close()

    asyncio.run(_main())
