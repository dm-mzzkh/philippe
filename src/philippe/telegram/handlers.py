"""Wire Telegram updates to the engine: /start, button taps, and messages."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from ..context import resolve_context
from ..db.resolve import resolve_form
from ..dialog import Cancelled, Completed, Engine, Session, Show
from ..dialog.engine import BACK
from ..fields.base import Button, Input, InputKind, Prompt
from ..fields.select import SelectSpec
from .keyboards import build_keyboard
from .render import message_to_input

logger = logging.getLogger("philippe.telegram")

# Payload of a "pick this form" button in the /forms menu (adapter-level, the
# engine knows nothing about there being multiple forms).
FORM_PREFIX = "__form__:"
# Payload of an actionable query-view row button: tapping launches the view's
# `action` form, prefilled from that row.
ACTION_PREFIX = "__act__:"

# A persistent reply keyboard with a single shortcut to the /forms menu, kept
# above the user's keyboard at all times (set once on /start).
FORMS_BUTTON = "📋 Forms"
FORMS_REPLY_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=FORMS_BUTTON)]],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Tap 📋 Forms to pick a form",
)


class Runner:
    """Holds the form/engine/store and drives one engine step to a rendered reply."""

    def __init__(self, forms, sink, store, catalog=None, transcriber=None) -> None:
        self.forms = forms  # dict: name -> FormSpec
        self.sink = sink
        self.store = store
        self.catalog = catalog
        self.transcriber = transcriber
        self.engine = Engine()
        self._buttons: dict[int, list[str]] = {}  # chat_id -> last payloads
        self._actions: dict[int, tuple] = {}      # chat_id -> (QueryAction, rows)

    async def new_session(self, name: str) -> Session:
        """Resolve the chosen form's dynamic options (off the event loop) and
        start a session for it."""
        base = self.forms[name]
        has_dynamic = any(
            isinstance(s, SelectSpec) and s.is_dynamic for s in base.fields
        )
        if has_dynamic:
            form = await asyncio.to_thread(resolve_form, base, self.catalog)
        else:
            form = resolve_form(base, self.catalog)  # cheap copy, no DB
        return Session(form=form)

    # --- the /forms menu --------------------------------------------------

    def _menu_prompt(self) -> Prompt:
        if not self.forms:
            return Prompt("No forms are available.", [], {InputKind.BUTTON})
        rows = [[Button(f.title, FORM_PREFIX + name)] for name, f in self.forms.items()]
        return Prompt("Pick a form to fill:", rows, {InputKind.BUTTON})

    async def show_menu(self, message: Message, *, edit: bool = False) -> None:
        prompt = self._menu_prompt()
        markup, payloads = build_keyboard(prompt)
        self._buttons[message.chat.id] = payloads
        if edit:
            try:
                await message.edit_text(prompt.text, reply_markup=markup)
            except TelegramBadRequest:
                pass
        else:
            await message.answer(prompt.text, reply_markup=markup)

    async def start_form(
        self, message: Message, name: str, *, edit: bool, prefill: dict | None = None
    ) -> None:
        form = self.forms.get(name)
        if form is None:
            await message.answer("That form is no longer available — /forms")
            return
        if form.kind == "query":
            await self._run_query(message, form, edit=edit)
            return
        try:
            session = await self.new_session(name)
        except Exception as e:
            logger.exception("could not start form '%s'", name)
            await message.answer(f"⚠️ Could not start: {e}")
            return
        outcome = self.engine.start(session, prefill=prefill)
        await self.resolve(message, session, outcome, edit=edit)

    async def _run_query(self, message: Message, form, *, edit: bool) -> None:
        """Run a `kind: query` view and show its rows as a plain text list.
        Each row's `label` column becomes one line."""
        if self.catalog is None:
            await message.answer("⚠️ This view needs a database.")
            return
        try:
            rows = await asyncio.to_thread(self.catalog.query, form.query)
        except Exception as e:
            logger.exception("query failed for form '%s'", form.name)
            await message.answer(f"⚠️ Could not load: {e}")
            return

        chat_id = message.chat.id
        if not rows:
            self._buttons.pop(chat_id, None)
            self._actions.pop(chat_id, None)
            await self._render_text(message, f"{form.title}\n\n— всё сделано 🎉",
                                    markup=None, edit=edit)
            return

        if form.action is None:  # plain read-only list
            self._buttons.pop(chat_id, None)
            self._actions.pop(chat_id, None)
            lines = "\n".join(f"• {row.get('label', row)}" for row in rows)
            await self._render_text(message, f"{form.title}\n\n{lines}",
                                    markup=None, edit=edit)
            return

        # actionable view: one button per row → tap launches form.action
        prompt = Prompt(
            form.title,
            [[Button(str(row.get("label", row)), ACTION_PREFIX + str(i))]
             for i, row in enumerate(rows)],
            {InputKind.BUTTON},
        )
        markup, payloads = build_keyboard(prompt)
        self._buttons[chat_id] = payloads
        self._actions[chat_id] = (form.action, rows)
        await self._render_text(message, prompt.text, markup=markup, edit=edit)

    async def _render_text(self, message, text, *, markup, edit) -> None:
        if edit:
            try:
                await message.edit_text(text, reply_markup=markup)
            except TelegramBadRequest:
                pass
        else:
            await message.answer(text, reply_markup=markup)

    def action_prefill(self, chat_id: int, row_index: int) -> tuple | None:
        """Resolve a tapped query-row → (target form name, prefill dict)."""
        action, rows = self._actions.get(chat_id, (None, None))
        if action is None or not (0 <= row_index < len(rows)):
            return None
        row = rows[row_index]
        prefill = {field: row[col] for field, col in action.prefill.items()}
        return action.form, prefill

    def _context(self, message: Message, form) -> dict:
        """Resolve the form's context columns from the Telegram message."""
        if not form.context:
            return {}
        user = message.from_user
        username = f"@{user.username}" if user and user.username else None
        available = {
            "user_id": user.id if user else None,
            "user_name": username or (user.full_name if user else None),
            "chat_id": message.chat.id,
        }
        return resolve_context(form.context, available)

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
                record = {**outcome.record, **self._context(message, session.form)}
                try:
                    await asyncio.to_thread(self.sink.save, session.form, record)
                except Exception as e:  # keep the review so the user can retry/cancel
                    logger.exception("save failed for form '%s'", session.form.name)
                    await message.answer(f"⚠️ Could not save: {e}")
                    return
                if edit:  # drop the review keyboard now that it's committed
                    await self._strip_keyboard(message)
                    edit = False
                lines = ["✔ Saved:"] + [
                    f"• {label}: {value}" for label, value in outcome.rendered.items()
                ]
                await message.answer("\n".join(lines))
                if outcome.restart:
                    outcome = self.engine.restart(session)
                    continue
                self.store.drop(chat_id)
                self._actions.pop(chat_id, None)
                await self.show_menu(message, edit=edit)
                return
            if isinstance(outcome, Cancelled):
                # Cancel, or Back on the first field → drop the form and return
                # to the /forms menu (editing the message in place if from a tap).
                self.store.drop(chat_id)
                self._actions.pop(chat_id, None)
                await self.show_menu(message, edit=edit)
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


def build_dispatcher(runner: Runner, allowed_ids: set[int] | None = None) -> Dispatcher:
    router = Router()
    if allowed_ids:  # whitelist: ignore everyone else
        router.message.filter(F.from_user.id.in_(allowed_ids))
        router.callback_query.filter(F.from_user.id.in_(allowed_ids))

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        # Pin the persistent "📋 Forms" button above the keyboard, then show the menu.
        await message.answer("Кнопка «📋 Forms» всегда под рукой 👇",
                             reply_markup=FORMS_REPLY_KB)
        await runner.show_menu(message)

    @router.message(Command("forms"))
    @router.message(F.text == FORMS_BUTTON)
    async def on_forms(message: Message) -> None:
        await runner.show_menu(message)

    @router.callback_query()
    async def on_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        message = callback.message
        value = runner.button_value(message.chat.id, callback.data or "")
        if value is None:
            return
        if value.startswith(FORM_PREFIX):  # picked a form from the menu
            await runner.start_form(message, value[len(FORM_PREFIX):], edit=True)
            return
        if value.startswith(ACTION_PREFIX):  # tapped a row in an actionable view
            resolved = runner.action_prefill(
                message.chat.id, int(value[len(ACTION_PREFIX):])
            )
            if resolved is not None:
                form_name, prefill = resolved
                await runner.start_form(message, form_name, edit=True, prefill=prefill)
            return
        session = runner.store.get(message.chat.id)
        if session is None:
            await message.answer("Session expired — send /forms.")
            return
        inp = Input(back=True) if value == BACK else Input(button=value)
        await runner.drive(message, session, inp, edit=True)  # update in place

    @router.message()
    async def on_message(message: Message) -> None:
        session = runner.store.get(message.chat.id)
        if session is None:
            await message.answer("Send /forms to pick a form.")
            return
        inp = message_to_input(message, runner.transcriber)
        await runner.drive(message, session, inp)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
