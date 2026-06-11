"""Compose the Telegram adapter and start long-polling."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from ..forms.models import FormSpec
from ..sink import LoggingSink
from ..sink.base import RecordSink
from ..state import MemorySessionStore
from ..state.store import SessionStore
from .handlers import Runner, build_dispatcher

logger = logging.getLogger("philippe.telegram")


def run_bot(
    form: FormSpec,
    token: str,
    sink: RecordSink | None = None,
    store: SessionStore | None = None,
) -> None:
    runner = Runner(form, sink or LoggingSink(), store or MemorySessionStore())
    dispatcher = build_dispatcher(runner)
    bot = Bot(token)

    async def _main() -> None:
        logger.info("starting bot for form '%s'", form.name)
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await dispatcher.start_polling(bot)
        finally:
            await bot.session.close()

    asyncio.run(_main())
