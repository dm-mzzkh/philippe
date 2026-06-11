"""Wire Telegram updates to the engine: /start, button taps, and messages."""

from __future__ import annotations

import logging

from aiogram import Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from ..dialog import Cancelled, Completed, Engine, Session, Show
from ..dialog.engine import BACK
from ..fields.base import Input
from .keyboards import build_keyboard
from .render import message_to_input

logger = logging.getLogger("philippe.telegram")


class Runner:
    """Holds the form/engine/store and drives one engine step to a rendered reply."""

    def __init__(self, form, sink, store, transcriber=None) -> None:
        self.form = form
        self.sink = sink
        self.store = store
        self.transcriber = transcriber
        self.engine = Engine()
        self._buttons: dict[int, list[str]] = {}  # chat_id -> last payloads

    async def _send(self, message: Message, outcome: Show) -> None:
        """Reply with a brand-new message (after a text input or /start)."""
        markup, payloads = build_keyboard(outcome.prompt)
        self._buttons[message.chat.id] = payloads
        await message.answer(outcome.prompt.text, reply_markup=markup)

    async def _edit(self, message: Message, outcome: Show) -> None:
        """Update the existing message in place (after a button tap), so taps
        like picking a period then a ×N don't re-send the message."""
        markup, payloads = build_keyboard(outcome.prompt)
        self._buttons[message.chat.id] = payloads
        try:
            await message.edit_text(outcome.prompt.text, reply_markup=markup)
        except TelegramBadRequest:
            pass  # identical content (e.g. re-tapping the already-selected button)

    async def _strip_keyboard(self, message: Message) -> None:
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

    async def resolve(
        self, message: Message, session: Session, outcome, *, edit: bool = False
    ) -> None:
        chat_id = message.chat.id
        while True:
            if isinstance(outcome, Show):
                self.store.put(chat_id, session)
                if edit:
                    await self._edit(message, outcome)
                else:
                    await self._send(message, outcome)
                return
            if isinstance(outcome, Completed):
                if edit:  # drop the review keyboard before posting the result
                    await self._strip_keyboard(message)
                    edit = False
                self.sink.save(self.form, outcome.record)
                lines = ["✔ Saved:"] + [
                    f"• {label}: {value}" for label, value in outcome.rendered.items()
                ]
                await message.answer("\n".join(lines))
                outcome = self.engine.restart(session)
                continue
            if isinstance(outcome, Cancelled):
                if edit:
                    await self._strip_keyboard(message)
                self.store.drop(chat_id)
                self._buttons.pop(chat_id, None)
                await message.answer("Cancelled. Send /start to begin again.")
                return

    async def drive(
        self, message: Message, session: Session, inp: Input, *, edit: bool = False
    ) -> None:
        await self.resolve(message, session, self.engine.step(session, inp), edit=edit)

    def button_value(self, chat_id: int, data: str) -> str | None:
        try:
            return self._buttons.get(chat_id, [])[int(data)]
        except (ValueError, IndexError):
            return None


def build_dispatcher(runner: Runner) -> Dispatcher:
    router = Router()

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        session = Session(form=runner.form)
        await runner.resolve(message, session, runner.engine.start(session))

    @router.callback_query()
    async def on_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        message = callback.message
        session = runner.store.get(message.chat.id)
        if session is None:
            await message.answer("Session expired — send /start.")
            return
        value = runner.button_value(message.chat.id, callback.data or "")
        if value is None:
            return
        inp = Input(back=True) if value == BACK else Input(button=value)
        await runner.drive(message, session, inp, edit=True)  # update in place

    @router.message()
    async def on_message(message: Message) -> None:
        session = runner.store.get(message.chat.id)
        if session is None:
            await message.answer("Send /start to begin.")
            return
        inp = message_to_input(message, runner.transcriber)
        await runner.drive(message, session, inp)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
