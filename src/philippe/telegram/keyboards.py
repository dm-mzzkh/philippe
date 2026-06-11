"""Translate a :class:`Prompt` into an inline keyboard.

Button payloads can be long (select options, edit links), so callback data is
the button's *index* in the message; the handler keeps the index→value map per
chat. This sidesteps Telegram's 64-byte callback-data limit entirely.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..fields.base import Prompt


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
