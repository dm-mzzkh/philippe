"""Philippe — a Telegram bot that fills database records from form.yaml dialogs."""

from .core import (
    BACK,
    CANCEL,
    Cancelled,
    Completed,
    EDIT_PREFIX,
    Engine,
    FieldSpec,
    FormError,
    FormSpec,
    Input,
    OptionSource,
    Outcome,
    Recurrence,
    SelectSpec,
    Session,
    Show,
    SKIP,
    SUBMIT,
    get_field_type,
    form_needs_db,
    load_form,
    resolve_context,
    resolve_form,
)
from ._db import LoggingSink, SqlCatalog, SqlSink, connect
from ._telegram import run_bot

__all__ = [
    "BACK", "CANCEL", "Cancelled", "Completed", "EDIT_PREFIX",
    "Engine", "FieldSpec", "FormError", "FormSpec",
    "Input", "LoggingSink", "OptionSource", "Outcome",
    "Recurrence", "SelectSpec", "Session", "Show", "SKIP", "SUBMIT",
    "SqlCatalog", "SqlSink", "connect",
    "get_field_type", "form_needs_db", "load_form",
    "resolve_context", "resolve_form", "run_bot",
]

__version__ = "0.1.0"