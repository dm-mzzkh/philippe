"""Telegram driving adapter (aiogram)."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from .core import (
    BACK,
    CANCEL,
    Cancelled,
    Completed,
    Engine,
    FormSpec,
    Input,
    InputKind,
    Prompt,
    Session,
    Show,
    Button as CoreButton,
    form_needs_db,
    get_field_type,
    resolve_context,
    resolve_form,
)
from ._hydrus import HydrusClient

logger = logging.getLogger("philippe.telegram")


FORM_PREFIX = "__form__:"
ACTION_PREFIX = "__act__:"

FORMS_BUTTON = "📋 Forms"
FORMS_REPLY_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=FORMS_BUTTON)]],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Tap 📋 Forms to pick a form",
)


def build_keyboard(prompt: Prompt) -> tuple[InlineKeyboardMarkup | None, list[str]]:
    rows: list[list[InlineKeyboardButton]] = []
    payloads: list[str] = []
    for row in prompt.buttons:
        krow = []
        for button in row:
            krow.append(
                InlineKeyboardButton(text=button.label, callback_data=str(len(payloads)))
            )
            payloads.append(button.value)
        if krow:
            rows.append(krow)
    markup = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    return markup, payloads


def message_to_input(message: Message) -> Input:
    if message.photo:
        return Input(attachment=Attachment(InputKind.PHOTO, message.photo[-1].file_id))
    if message.document:
        doc = message.document
        return Input(attachment=Attachment(InputKind.DOCUMENT, doc.file_id, doc.file_name))
    if message.audio:
        return Input(attachment=Attachment(InputKind.AUDIO, message.audio.file_id,
                                           message.audio.file_name))
    if message.voice:
        return Input(attachment=Attachment(InputKind.VOICE, message.voice.file_id))
    return Input(text=message.text or "")


# ponytail: dict[int, Session] beats a three-file Protocol-wrapped store
from .core import Attachment, SelectSpec


class Runner:
    def __init__(self, forms, sink, catalog=None, hydrus_client=None, host=None):
        self.forms = forms
        self.sink = sink
        self.catalog = catalog
        self.hydrus_client = hydrus_client
        # Which machine is this bot running on — shown in /start.
        self.host = host or os.environ.get("PHILIPPE_HOST") or socket.gethostname()
        self.engine = Engine()
        self._sessions: dict[int, Session] = {}
        self._buttons: dict[int, list[str]] = {}
        self._actions: dict[int, tuple] = {}
        # MVP hourly check-in state: chat_id -> (hour_start, message_id).
        # ponytail: in-memory only; a reboot loses the pending question — fine,
        # missed hours are skipped by design.
        self._pending: dict[int, tuple[datetime, int]] = {}

    async def new_session(self, name: str) -> Session:
        base = self.forms[name]
        has_dynamic = any(
            isinstance(s, SelectSpec) and s.is_dynamic for s in base.fields
        )
        if has_dynamic:
            form = await asyncio.to_thread(resolve_form, base, self.catalog)
        else:
            form = resolve_form(base, self.catalog)
        return Session(form=form)

    def _menu_prompt(self) -> Prompt:
        if not self.forms:
            return Prompt("No forms are available.", [], {InputKind.BUTTON})
        rows = [[CoreButton(f.title, FORM_PREFIX + name)]
                for name, f in self.forms.items()]
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
            text = f"{form.title}\n\n— всё сделано 🎉"
            await self._render_text(message, text, markup=None, edit=edit)
            return

        if form.action is None:
            self._buttons.pop(chat_id, None)
            self._actions.pop(chat_id, None)
            lines = "\n".join(f"• {row.get('label', row)}" for row in rows)
            await self._render_text(message, f"{form.title}\n\n{lines}",
                                    markup=None, edit=edit)
            return

        prompt = Prompt(
            form.title,
            [[CoreButton(str(row.get("label", row)), ACTION_PREFIX + str(i))]
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

    async def show_row_images(self, message: Message, row_index: int) -> None:
        """Send the photos a query row references (action.show_images column)."""
        if self.hydrus_client is None:
            await message.answer("⚠️ Hydrus is not configured.")
            return
        action, rows = self._actions.get(message.chat.id, (None, None))
        if action is None or not (0 <= row_index < len(rows)):
            return
        hashes = rows[row_index].get(action.show_images) or []
        if not hashes:
            await message.answer("Нет фото 📭")
            return
        # ponytail: Telegram media groups cap at 10; extra photos dropped — rare per review.
        hashes = hashes[:10]

        def _fetch():
            return [self.hydrus_client.thumbnail(h) for h in hashes]

        blobs = await asyncio.to_thread(_fetch)
        media = [InputMediaPhoto(media=BufferedInputFile(b, f"{i}.jpg"))
                 for i, b in enumerate(blobs)]
        if len(media) == 1:
            await message.answer_photo(media[0].media)
        else:
            await message.bot.send_media_group(message.chat.id, media=media)

    def action_prefill(self, chat_id: int, row_index: int) -> tuple | None:
        action, rows = self._actions.get(chat_id, (None, None))
        if action is None or not (0 <= row_index < len(rows)):
            return None
        row = rows[row_index]
        prefill = {field: row[col] for field, col in action.prefill.items()}
        return action.form, prefill

    def _context(self, message: Message, form) -> dict:
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

    async def _show(self, message: Message, outcome: Show, *, edit: bool) -> None:
        markup, payloads = build_keyboard(outcome.prompt)
        self._buttons[message.chat.id] = payloads
        if edit:
            try:
                await message.edit_text(outcome.prompt.text, reply_markup=markup)
            except TelegramBadRequest:
                pass
        else:
            await message.answer(outcome.prompt.text, reply_markup=markup)

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
                self._sessions[chat_id] = session
                await self._show(message, outcome, edit=edit)
                return
            if isinstance(outcome, Completed):
                record = {**outcome.record, **self._context(message, session.form)}
                try:
                    await self._persist_images(message, session, record)
                    await asyncio.to_thread(self.sink.save, session.form, record)
                except Exception as e:
                    logger.exception("save failed for form '%s'", session.form.name)
                    await message.answer(f"⚠️ Could not save: {e}")
                    return
                if edit:
                    await self._strip_keyboard(message)
                    edit = False
                lines = ["✔ Saved:"] + [
                    f"• {label}: {value}" for label, value in outcome.rendered.items()
                ]
                await message.answer("\n".join(lines))
                if outcome.restart:
                    outcome = self.engine.restart(session)
                    continue
                self._sessions.pop(chat_id, None)
                self._actions.pop(chat_id, None)
                await self.show_menu(message, edit=edit)
                return
            if isinstance(outcome, Cancelled):
                self._sessions.pop(chat_id, None)
                self._actions.pop(chat_id, None)
                await self.show_menu(message, edit=edit)
                return

    async def _persist_images(self, message: Message, session: Session, record: dict) -> None:
        """Download each photos-field's blobs, upload to Hydrus, replace file_ids
        with content hashes, and apply tags from the field spec."""
        if self.hydrus_client is None:
            return
        for spec in session.form.fields:
            if spec.type != "photos":
                continue
            col = get_field_type(spec.type).column(spec)
            file_ids = record.get(col) or []
            if not file_ids:
                continue
            hashes = []
            for fid in file_ids:
                data = (await message.bot.download(fid)).read()
                h = await asyncio.to_thread(self.hydrus_client.upload, data)
                hashes.append(h)
            if spec.tags:
                resolved = [str(session.answers.get(t, t)) for t in spec.tags]
                for h in hashes:
                    await asyncio.to_thread(self.hydrus_client.tag, h, resolved)
            record[col] = hashes

    async def drive(
        self, message: Message, session: Session, inp: Input, *, edit: bool = False
    ) -> None:
        await self.resolve(message, session, self.engine.step(session, inp), edit=edit)

    def button_value(self, chat_id: int, data: str) -> str | None:
        try:
            return self._buttons.get(chat_id, [])[int(data)]
        except (ValueError, IndexError):
            return None

    async def save_hour_reply(self, message: Message, period: datetime) -> None:
        """Store one reply: text line into hour_log, photos into hour_photos.
        Re-replies to the same question OVERWRITE: text replaces the note,
        photos for the period are reset to the new set. The bot never sends
        the photos back — too heavy."""
        note = (message.text or message.caption or "").strip()
        photos = message.photo or []
        if not note and not photos:
            await message.answer("Пусто — нужен текст или фото.")
            return
        record = {"period": period, "note": note}
        record.update(self._context(message, self.forms["hour"]))
        try:
            if note:
                # ponytail: UPDATE-or-INSERT via rowcount beats ON CONFLICT
                # here because the sink API is form-shaped; fine at 1 row/hour.
                cur = await asyncio.to_thread(
                    self.sink.exec,
                    'UPDATE hour_log SET note = %s::text '
                    'WHERE period = %s::timestamptz RETURNING id',
                    [note, period],
                )
                if cur is None:  # no existing row for this period
                    await asyncio.to_thread(self.sink.save, self.forms["hour"], record)
            # photos always reset: the new reply's set replaces the old one
            await asyncio.to_thread(
                self.sink.exec,
                "DELETE FROM hour_photos WHERE period = %s::timestamptz",
                [period],
            )
            for _ in photos:
                await self._save_hour_photo(message, period)
        except Exception as e:
            logger.exception("hour check-in save failed")
            await message.answer(f"⚠️ Could not save: {e}")
            return
        parts = []
        if note:
            words = " ".join(note.split())
            # ponytail: MVP — 10 words then ellipsis, was measured against a
            # favourite example; raise the cap if long entries matter.
            words = " ".join(words.split()[:10]) + "…" if len(words.split()) > 10 else words
            parts.append(f'✔ Записал: "{words}"')
        if photos:
            parts.append(f"• 📷 {len(photos)}")
        await message.answer("\n".join(parts))

    async def _save_hour_photo(self, message: Message, period: datetime) -> None:
        """One photo -> one hour_photos row. Hydrus hash when configured,
        raw Telegram file_id otherwise (ponytail: no hydrus integration for
        hourly check-ins)."""
        file_id = message.photo[-1].file_id
        hash_ = file_id
        if self.hydrus_client is not None:
            data = (await message.bot.download(file_id)).read()
            hash_ = await asyncio.to_thread(self.hydrus_client.upload, data)
        await asyncio.to_thread(
            self.sink.insert, "hour_photos",
            {"period": period, "hash": hash_, "chat_id": message.chat.id},
        )


# ---------------------------------------------------------------------------
# MVP hourly check-in scheduler
# ---------------------------------------------------------------------------

# ponytail: MVP hack hourly nag — one target chat, in-memory pending state,
# no catch-up for missed hours. Add persistence/queue only if that bites.

HOUR_ASK_MINUTE = 0  # ask right at :00 about the hour that just ended


def _local_now() -> datetime:
    """Wall-clock time for the hourly check-in. PHILIPPE_TZ (IANA name) wins;
    containers have no local tz, so without it we'd nag in UTC."""
    name = os.environ.get("PHILIPPE_TZ")
    if name:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(name))
    return datetime.now().astimezone()


async def hour_nag_loop(runner: Runner, bot: Bot, chat_id: int) -> None:
    """Every hour at :15 ask the target chat what it did the hour before.

    The bot waits for a *reply* to exactly this question; the reply is stored
    as one free-text row. Non-replies are left alone entirely.
    """
    logger.info("hourly check-in nagging chat %s", chat_id)
    asked_for = None
    while True:
        now = _local_now()
        anchor = now.replace(minute=0, second=0, microsecond=0)
        if asked_for is None or asked_for < anchor:
            if now.minute >= HOUR_ASK_MINUTE:
                prev = anchor - timedelta(hours=1)  # the hour just ended
                text = f"❓ Что делал за {prev:%H:%M}–{anchor:%H:%M}?"
                msg = await bot.send_message(chat_id, text)
                runner._pending[chat_id] = (prev, msg.message_id)
                asked_for = anchor
        # sleep until next hour's :15:05
        wake = anchor + timedelta(hours=1, minutes=HOUR_ASK_MINUTE, seconds=5)
        await asyncio.sleep(max((wake - now).total_seconds(), 5.0))


def build_dispatcher(runner: Runner, allowed_ids: set[int] | None = None) -> Dispatcher:
    router = Router()
    if allowed_ids:
        router.message.filter(F.from_user.id.in_(allowed_ids))
        router.callback_query.filter(F.from_user.id.in_(allowed_ids))

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        await message.answer("Кнопка «📋 Forms» всегда под рукой 👇\n"
                             f"🤖 Запущен на: {runner.host}",
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
        if value.startswith(FORM_PREFIX):
            await runner.start_form(message, value[len(FORM_PREFIX):], edit=True)
            return
        if value.startswith(ACTION_PREFIX):
            idx = int(value[len(ACTION_PREFIX):])
            action, _ = runner._actions.get(message.chat.id, (None, None))
            if action is not None and action.show_images:
                await runner.show_row_images(message, idx)
                return
            resolved = runner.action_prefill(message.chat.id, idx)
            if resolved is not None:
                form_name, prefill = resolved
                await runner.start_form(message, form_name, edit=True, prefill=prefill)
            return
        session = runner._sessions.get(message.chat.id)
        if session is None:
            await message.answer("Session expired — send /forms.")
            return
        inp = Input(back=True) if value == BACK else Input(button=value)
        await runner.drive(message, session, inp, edit=True)

    @router.message()
    async def on_message(message: Message) -> None:
        chat_id = message.chat.id
        # Hourly check-in: only a reply to the bot's current question counts.
        pending = runner._pending.get(chat_id)
        if (pending is not None and message.reply_to_message
                and message.reply_to_message.message_id == pending[1]):
            # pending stays alive until the next hourly question — a newer
            # reply to the same question just overwrites period's row.
            await runner.save_hour_reply(message, pending[0])
            return
        session = runner._sessions.get(chat_id)
        if session is None:
            await message.answer("Send /forms to pick a form.")
            return
        inp = message_to_input(message)
        await runner.drive(message, session, inp)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


def run_bot(
    forms: dict[str, FormSpec],
    token: str,
    sink,
    catalog=None,
    hydrus_client=None,
    allowed_ids: set[int] | None = None,
    hour_chat: int | None = None,
) -> None:
    runner = Runner(forms, sink, catalog=catalog,
                    hydrus_client=hydrus_client,
                    host=os.environ.get("PHILIPPE_HOST"))
    dispatcher = build_dispatcher(runner, allowed_ids=allowed_ids)
    bot = Bot(token)

    async def _main() -> None:
        from aiogram.types import BotCommand
        logger.info("starting bot with forms: %s%s", ", ".join(forms),
                    f" (whitelist: {len(allowed_ids)} ids)" if allowed_ids else "")
        if hour_chat is not None:
            asyncio.create_task(hour_nag_loop(runner, bot, hour_chat))
        else:
            logger.info("PHILIPPE_HOUR_CHAT unset — hourly check-in disabled")
        try:
            await bot.set_my_commands([
                BotCommand(command="forms", description="List forms to fill"),
                BotCommand(command="start", description="List forms to fill"),
            ])
            announce_to = hour_chat or (sorted(allowed_ids)[0] if allowed_ids else None)
            if announce_to:
                try:
                    await bot.send_message(announce_to,
                                           f"🤖 Бот поднялся на: {runner.host}")
                except Exception:
                    logger.exception("startup announce failed")
            await bot.delete_webhook(drop_pending_updates=True)
            await dispatcher.start_polling(bot)
        finally:
            await bot.session.close()

    asyncio.run(_main())