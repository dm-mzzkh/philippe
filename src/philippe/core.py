"""Domain core: models, field types, engine, loader, context, resolve.

A single flat module so nothing can circular-import. Everything here is pure
Python — no I/O, no Telegram, no Postgres.
"""

from __future__ import annotations

import copy
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date as _date, timedelta, time as _time
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator
from pydantic import ValidationError  # noqa: F401  re-exported for callers

logger = logging.getLogger("philippe.core")


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class FormError(Exception):
    """A ``form.yaml`` could not be read, parsed, or validated."""


# ---------------------------------------------------------------------------
# Spec models  (pydantic — validated directly from the YAML)
# ---------------------------------------------------------------------------

class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    type: str
    label: str
    required: bool = True
    default: Any = None
    help: str | None = None
    column: str | None = None
    show_if: dict[str, Any] | None = None
    tags: list[str] = []


class NumberSpec(FieldSpec):
    min: float | None = None
    max: float | None = None
    presets: list[float] | None = None

    @model_validator(mode="after")
    def _check(self) -> "NumberSpec":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("'min' must be <= 'max'")
        return self


class OptionSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str | None = None
    value: str | None = None
    label: str | None = None
    where: str | None = None
    order_by: str | None = None
    query: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "OptionSource":
        structured = ("table", "value", "label", "where", "order_by")
        if self.query:
            used = [k for k in structured if getattr(self, k)]
            if used:
                raise ValueError(f"'query' cannot be combined with {used}")
        else:
            missing = [k for k in ("table", "value", "label") if not getattr(self, k)]
            if missing:
                raise ValueError(f"option source needs {missing} (or a raw 'query' instead)")
        return self


class SelectSpec(FieldSpec):
    options: list[str] | OptionSource
    allow_custom: bool = False

    _choices: list[tuple[str, Any]] | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _check(self) -> "SelectSpec":
        if isinstance(self.options, list):
            if not self.options:
                raise ValueError("'options' must list at least one choice")
            if self.default is not None and self.default not in self.options:
                raise ValueError(f"'default' {self.default!r} is not one of options")
        return self

    @property
    def is_dynamic(self) -> bool:
        return isinstance(self.options, OptionSource)

    def choices(self) -> list[tuple[str, Any]]:
        if self._choices is not None:
            return self._choices
        if isinstance(self.options, list):
            return [(opt, opt) for opt in self.options]
        raise RuntimeError(f"select '{self.key}' has dynamic options that were not resolved")

    def set_choices(self, choices: list[tuple[str, Any]]) -> None:
        self._choices = list(choices)


class RepeatSpec(FieldSpec):
    period_column: str = "period"
    every_column: str = "every"


class QueryAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form: str | None = None
    prefill: dict[str, str] = {}
    # Instead of starting a form, send the photos a row references: the named
    # column must hold a TEXT[] of image hashes (see the `photos` field type).
    show_images: str | None = None

    @model_validator(mode="after")
    def _exactly_one_action(self) -> "QueryAction":
        if bool(self.form) == bool(self.show_images):
            raise ValueError("action needs exactly one of 'form' or 'show_images'")
        return self


class ContextColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    column: str
    source: str = Field(alias="from")


# ---------------------------------------------------------------------------
# Form container  (plain dataclass — already validated by then)
# ---------------------------------------------------------------------------

@dataclass
class FormSpec:
    name: str
    title: str
    table: str | None
    fields: list[FieldSpec]
    context: list[ContextColumn] = field(default_factory=list)
    kind: str = "form"
    query: str | None = None
    action: QueryAction | None = None
    labels: dict[str, str] = field(default_factory=dict)
    submit_once: bool = False

    def field_index(self, key: str) -> int:
        for i, spec in enumerate(self.fields):
            if spec.key == key:
                return i
        raise KeyError(key)


# ---------------------------------------------------------------------------
# Value types  (exchanged between the engine, fields, and adapter)
# ---------------------------------------------------------------------------

class InputKind(str, Enum):
    TEXT = "text"
    BUTTON = "button"
    VOICE = "voice"
    PHOTO = "photo"
    DOCUMENT = "document"
    AUDIO = "audio"


@dataclass(frozen=True)
class Button:
    label: str
    value: str


@dataclass(frozen=True)
class Attachment:
    kind: InputKind
    file_id: str
    file_name: str | None = None


@dataclass
class Prompt:
    text: str
    buttons: list[list[Button]] = field(default_factory=list)
    expect: set[InputKind] = field(default_factory=lambda: {InputKind.TEXT})


@dataclass
class Input:
    text: str | None = None
    button: str | None = None
    attachment: Attachment | None = None
    back: bool = False


@dataclass
class Ask:
    prompt: Prompt


@dataclass
class Done:
    value: Any


Step = Ask | Done


# ---------------------------------------------------------------------------
# Field type base
# ---------------------------------------------------------------------------

class FieldType(ABC):
    spec_model: ClassVar[type[FieldSpec]] = FieldSpec

    @abstractmethod
    def start(self, spec: FieldSpec, fstate: dict) -> Prompt: ...

    @abstractmethod
    def handle(self, spec: FieldSpec, fstate: dict, inp: Input) -> Step: ...

    def render(self, spec: FieldSpec, value: Any) -> str:
        return str(value)

    def to_record(self, spec: FieldSpec, value: Any) -> Any:
        return value

    def column(self, spec: FieldSpec) -> str:
        return spec.column or spec.key

    def columns(self, spec: FieldSpec) -> list[str]:
        return [self.column(spec)]

    def to_columns(self, spec: FieldSpec, value: Any) -> dict[str, Any]:
        return {self.column(spec): self.to_record(spec, value)}


# ---------------------------------------------------------------------------
# Field type implementations
# ---------------------------------------------------------------------------

class Text(FieldType):
    spec_model = FieldSpec

    def start(self, spec, fstate):
        return Prompt(spec.label, expect={InputKind.TEXT, InputKind.VOICE})

    def handle(self, spec, fstate, inp):
        if inp.text and inp.text.strip():
            return Done(inp.text.strip())
        return Ask(Prompt("Please type some text (or send a voice message).",
                          expect={InputKind.TEXT, InputKind.VOICE}))


def _fmt(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def _coerce(raw: str) -> float:
    return float(raw.replace(",", ".").strip())


class Number(FieldType):
    spec_model = NumberSpec

    def _keyboard(self, spec: NumberSpec):
        if not spec.presets:
            return []
        return [[Button(_fmt(p), _fmt(p)) for p in spec.presets]]

    def _hint(self, spec: NumberSpec) -> str:
        if spec.min is not None and spec.max is not None:
            return f"{spec.label} ({_fmt(spec.min)}–{_fmt(spec.max)})"
        if spec.min is not None:
            return f"{spec.label} (≥ {_fmt(spec.min)})"
        if spec.max is not None:
            return f"{spec.label} (≤ {_fmt(spec.max)})"
        return spec.label

    def start(self, spec, fstate):
        return Prompt(self._hint(spec), self._keyboard(spec),
                      {InputKind.TEXT, InputKind.BUTTON})

    def handle(self, spec, fstate, inp):
        raw = inp.button if inp.button is not None else inp.text
        try:
            value = _coerce(raw or "")
        except (TypeError, ValueError):
            return Ask(Prompt("Please enter a number.", self._keyboard(spec),
                              {InputKind.TEXT, InputKind.BUTTON}))
        if value.is_integer():
            value = int(value)
        if spec.min is not None and value < spec.min:
            return Ask(Prompt(f"Must be at least {_fmt(spec.min)}.", self._keyboard(spec),
                              {InputKind.TEXT, InputKind.BUTTON}))
        if spec.max is not None and value > spec.max:
            return Ask(Prompt(f"Must be at most {_fmt(spec.max)}.", self._keyboard(spec),
                              {InputKind.TEXT, InputKind.BUTTON}))
        return Done(value)

    def render(self, spec, value):
        return _fmt(value)


_YES = {"yes", "y", "да", "true", "1"}
_NO = {"no", "n", "нет", "false", "0"}


class Bool(FieldType):
    spec_model = FieldSpec

    def _keyboard(self, spec):
        yes, no = "Yes", "No"
        if spec.default is True:
            yes = "Yes (default)"
        elif spec.default is False:
            no = "No (default)"
        return [[Button(yes, "yes"), Button(no, "no")]]

    def start(self, spec, fstate):
        return Prompt(spec.label, self._keyboard(spec),
                      {InputKind.BUTTON, InputKind.TEXT})

    def handle(self, spec, fstate, inp):
        token = (inp.button or inp.text or "").strip().lower()
        if token in _YES:
            return Done(True)
        if token in _NO:
            return Done(False)
        return Ask(Prompt("Please tap Yes or No.", self._keyboard(spec),
                          {InputKind.BUTTON, InputKind.TEXT}))

    def render(self, spec, value):
        return "Yes" if value else "No"


_REL = [
    ("Day before yesterday", "rel:-2", -2),
    ("Yesterday", "rel:-1", -1),
    ("Today", "rel:0", 0),
    ("Tomorrow", "rel:1", 1),
]

_DEFAULT_DELTA: dict[str | None, int] = {None: 0, "today": 0, "yesterday": -1}

_WEEKDAYS = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6,
}


def _parse_typed_date(text: str, today: _date) -> _date:
    t = text.strip().lower()
    if t in _WEEKDAYS:
        return today + timedelta(days=_WEEKDAYS[t] - today.weekday())
    parts = [p for p in re.split(r"[.\s/]+", t) if p]
    if len(parts) == 2:
        day, month = int(parts[0]), int(parts[1])
        return _date(today.year, month, day)
    if len(parts) == 3:
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        if year < 100:
            year += 2000
        return _date(year, month, day)
    raise ValueError(f"unrecognized date: {text!r}")


class Date(FieldType):
    spec_model = FieldSpec

    def _keyboard(self, spec):
        row = []
        marked = _DEFAULT_DELTA.get(spec.default)
        for label, value, delta in _REL:
            mark = " (default)" if marked is not None and delta == marked else ""
            row.append(Button(label + mark, value))
        return [row[:2], row[2:]]

    def start(self, spec, fstate):
        return Prompt(spec.label, self._keyboard(spec),
                      {InputKind.BUTTON, InputKind.TEXT})

    def handle(self, spec, fstate, inp):
        today = _date.today()
        if inp.button and inp.button.startswith("rel:"):
            return Done(today + timedelta(days=int(inp.button[4:])))
        if inp.text:
            try:
                return Done(_parse_typed_date(inp.text, today))
            except ValueError:
                pass
        return Ask(Prompt(
            "Pick a day, or type a weekday / dd.mm / dd.mm.yyyy.",
            self._keyboard(spec), {InputKind.BUTTON, InputKind.TEXT},
        ))

    def render(self, spec, value: _date):
        return value.isoformat()

    def to_record(self, spec, value: _date):
        return value


_TIME_PATTERN = re.compile(r"(\d{1,2})[:.\s]?(\d{2})")


def _parse_time(text: str) -> _time:
    m = _TIME_PATTERN.fullmatch(text.strip())
    if not m:
        raise ValueError(f"not a time: {text!r}")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"out of range: {text!r}")
    return _time(hour, minute)


class Time(FieldType):
    spec_model = FieldSpec

    def start(self, spec, fstate):
        return Prompt(spec.label, expect={InputKind.TEXT})

    def handle(self, spec, fstate, inp):
        if inp.text:
            try:
                return Done(_parse_time(inp.text))
            except ValueError:
                pass
        return Ask(Prompt("Enter a time as HH:MM (e.g. 23:30).",
                          expect={InputKind.TEXT}))

    def render(self, spec, value: _time):
        return value.strftime("%H:%M")

    def to_record(self, spec, value: _time):
        return value


_PERIODS = [("Every day", "day"), ("Once a week", "week"), ("Once a month", "month")]
_PERIOD_VALUES = {value for _, value in _PERIODS}
_FREQ_BUTTONS = [1, 2, 3, 4]


@dataclass
class Recurrence:
    period: str
    frequency: int


def _mark(label: str, selected: bool) -> str:
    return f"• {label}" if selected else label


class Repeat(FieldType):
    spec_model = RepeatSpec

    def _prompt(self, fstate: dict, hint: str | None = None) -> Prompt:
        period = fstate.get("period")
        every = fstate.get("every")
        period_row = [
            Button(_mark(label, value == period), value) for label, value in _PERIODS
        ]
        freq_row = [
            Button(_mark(f"×{n}", n == every), str(n)) for n in _FREQ_BUTTONS
        ]
        text = hint or "How often does it repeat? Pick a period and ×N:"
        return Prompt(text, [period_row, freq_row], {InputKind.BUTTON, InputKind.TEXT})

    def start(self, spec, fstate):
        return self._prompt(fstate)

    def handle(self, spec, fstate, inp):
        token = (inp.button if inp.button is not None else inp.text or "").strip()

        if token in _PERIOD_VALUES:
            fstate["period"] = token
        else:
            try:
                every = int(token)
            except ValueError:
                every = 0
            if 1 <= every <= 365:
                fstate["every"] = every
            else:
                return Ask(self._prompt(
                    fstate, "Pick a period and ×N, or type a number from 1 to 365."
                ))

        if "period" in fstate and "every" in fstate:
            return Done(Recurrence(fstate["period"], fstate["every"]))
        return Ask(self._prompt(fstate))

    def render(self, spec, value: Recurrence):
        if value.frequency == 1:
            return f"every {value.period}"
        return f"every {value.frequency} {value.period}s"

    def to_record(self, spec, value: Recurrence):
        return {"period": value.period, "frequency": value.frequency}

    def columns(self, spec: RepeatSpec):
        return [spec.period_column, spec.every_column]

    def to_columns(self, spec: RepeatSpec, value: Recurrence):
        return {spec.period_column: value.period, spec.every_column: value.frequency}


class Select(FieldType):
    spec_model = SelectSpec

    def _keyboard(self, spec: SelectSpec):
        rows = []
        for label, value in spec.choices():
            shown = f"{label} (default)" if value == spec.default else label
            rows.append([Button(shown, str(value))])
        return rows

    def _expect(self, spec: SelectSpec):
        kinds = {InputKind.BUTTON}
        if spec.allow_custom:
            kinds.add(InputKind.TEXT)
        return kinds

    def start(self, spec, fstate):
        return Prompt(spec.label, self._keyboard(spec), self._expect(spec))

    def handle(self, spec, fstate, inp):
        if inp.button is not None:
            for _, value in spec.choices():
                if str(value) == inp.button:
                    return Done(value)
        if spec.allow_custom and inp.text and inp.text.strip():
            return Done(inp.text.strip())
        msg = "Please pick one of the options."
        if spec.allow_custom:
            msg = "Pick an option, or type your own value."
        return Ask(Prompt(msg, self._keyboard(spec), self._expect(spec)))

    def render(self, spec, value):
        for label, choice_value in spec.choices():
            if choice_value == value:
                return label
        return str(value)


class _AttachmentField(FieldType):
    accept: ClassVar[InputKind]
    noun: ClassVar[str]
    spec_model = FieldSpec

    def start(self, spec, fstate):
        return Prompt(spec.label, expect={self.accept})

    def handle(self, spec, fstate, inp):
        att = inp.attachment
        if att is not None and att.kind == self.accept:
            return Done(att)
        return Ask(Prompt(f"Please send {self.noun}.", expect={self.accept}))

    def render(self, spec, value: Attachment):
        return f"<{self.noun}: {value.file_name or value.file_id}>"

    def to_record(self, spec, value: Attachment):
        return value.file_id


class Photo(_AttachmentField):
    accept = InputKind.PHOTO
    noun = "a photo"


class Media(_AttachmentField):
    accept = InputKind.DOCUMENT
    noun = "a file"


class Audio(_AttachmentField):
    accept = InputKind.AUDIO
    noun = "an audio message"


PHOTOS_DONE = "__photos_done__"


class Photos(FieldType):
    """Collect many photos in one step; finish with a Done button.

    The dialog only accumulates Telegram file_ids (engine stays I/O-free). At
    submit the adapter downloads, hashes, and stores each blob in the `images`
    table, then swaps the file_ids for content hashes — so the field's column
    holds a TEXT[] of image hashes.
    """

    spec_model = FieldSpec
    _accept = {InputKind.PHOTO, InputKind.DOCUMENT}

    def _prompt(self, text: str) -> Prompt:
        return Prompt(text, [[Button("✅ Готово", PHOTOS_DONE)]],
                      self._accept | {InputKind.BUTTON})

    def start(self, spec, fstate):
        fstate["items"] = []
        return self._prompt(f"{spec.label}: пришли фото (можно несколько), "
                            "затем нажми «Готово».")

    def handle(self, spec, fstate, inp):
        items = fstate.setdefault("items", [])
        att = inp.attachment
        if att is not None and att.kind in self._accept:
            items.append(att)
            return Ask(self._prompt(f"📷 {len(items)} добавлено. Ещё или «Готово»."))
        if inp.button == PHOTOS_DONE:
            if items or not spec.required:
                return Done(list(items))
            return Ask(self._prompt("Пришли хотя бы одно фото."))
        return Ask(self._prompt("Пришли фото или нажми «Готово»."))

    def render(self, spec, value: list[Attachment]):
        return f"{len(value)} фото" if value else "—"

    def to_columns(self, spec, value: list[Attachment]):
        return {self.column(spec): [att.file_id for att in value]}


# ponytail: plain dict beats a decorator + auto-import registry
FIELD_TYPES: dict[str, FieldType] = {
    "title": Text(),
    "text": Text(),
    "number": Number(),
    "bool": Bool(),
    "date": Date(),
    "time": Time(),
    "repeat": Repeat(),
    "select": Select(),
    "photo": Photo(),
    "media": Media(),
    "audio": Audio(),
    "photos": Photos(),
}


def get_field_type(name: str) -> FieldType:
    try:
        return FIELD_TYPES[name]
    except KeyError:
        raise FormError(f"unknown field type '{name}'")


# ---------------------------------------------------------------------------
# Engine  (pure, synchronous state machine)
# ---------------------------------------------------------------------------

BACK = "__back__"
SKIP = "__skip__"
SUBMIT = "__submit__"
CANCEL = "__cancel__"
EDIT_PREFIX = "__edit__:"


@dataclass
class Session:
    form: FormSpec
    answers: dict[str, Any] = field(default_factory=dict)
    cursor: int = 0
    fstate: dict[str, dict] = field(default_factory=dict)
    mode: str = "filling"
    return_to_review: bool = False

    @property
    def current(self):
        return self.form.fields[self.cursor]


@dataclass
class Show:
    prompt: Prompt


@dataclass
class Completed:
    record: dict[str, Any]
    rendered: dict[str, str]
    restart: bool = True


@dataclass
class Cancelled:
    pass


Outcome = Show | Completed | Cancelled


class Engine:
    def start(self, session: Session, prefill: dict | None = None) -> Outcome:
        session.answers.clear()
        session.fstate.clear()
        session.mode = "filling"
        session.return_to_review = False
        if prefill:
            for key, value in prefill.items():
                session.answers[key] = value
        fields = session.form.fields
        session.cursor = 0
        while session.cursor < len(fields) and (
            fields[session.cursor].key in session.answers
            or not self._visible(fields[session.cursor], session.answers)
        ):
            session.cursor += 1
        if session.cursor >= len(fields):
            return self._show_review(session)
        return self._ask_current(session)

    def restart(self, session: Session) -> Outcome:
        return self.start(session)

    def step(self, session: Session, inp: Input) -> Outcome:
        if session.mode == "review":
            return self._step_review(session, inp)
        return self._step_filling(session, inp)

    def _step_filling(self, session: Session, inp: Input) -> Outcome:
        spec = session.current
        if inp.back:
            return self._go_back(session)
        if inp.button == SKIP and not spec.required:
            return self._store_and_advance(session, None)
        field_type = FIELD_TYPES[spec.type]
        fstate = session.fstate.setdefault(spec.key, {})
        result = field_type.handle(spec, fstate, inp)
        if isinstance(result, Ask):
            return Show(self._decorate(result.prompt, session))
        return self._store_and_advance(session, result.value)

    def _store_and_advance(self, session: Session, value: Any) -> Outcome:
        session.answers[session.current.key] = value
        if session.return_to_review:
            session.return_to_review = False
            return self._show_review(session)
        session.cursor += 1
        fields = session.form.fields
        while (session.cursor < len(fields)
               and not self._visible(fields[session.cursor], session.answers)):
            session.cursor += 1
        if session.cursor >= len(fields):
            return self._show_review(session)
        return self._ask_current(session)

    def _go_back(self, session: Session) -> Outcome:
        if session.return_to_review:
            session.return_to_review = False
            return self._show_review(session)
        if session.cursor == 0:
            return Cancelled()
        session.cursor -= 1
        fields = session.form.fields
        while (session.cursor > 0
               and not self._visible(fields[session.cursor], session.answers)):
            session.cursor -= 1
        return self._ask_current(session)

    def _ask_current(self, session: Session) -> Outcome:
        spec = session.current
        field_type = FIELD_TYPES[spec.type]
        fstate = session.fstate.setdefault(spec.key, {})
        prompt = field_type.start(spec, fstate)
        return Show(self._decorate(prompt, session))

    def _decorate(self, prompt: Prompt, session: Session) -> Prompt:
        row = []
        if not session.current.required:
            row.append(Button(session.form.labels.get("skip", "Skip"), SKIP))
        row.append(Button(session.form.labels.get("back", "◀ Back"), BACK))
        prompt.buttons = prompt.buttons + [row]
        return prompt

    def _show_review(self, session: Session) -> Outcome:
        session.mode = "review"
        buttons = []
        for spec in session.form.fields:
            if not self._visible(spec, session.answers):
                continue
            value = session.answers.get(spec.key)
            shown = (
                FIELD_TYPES[spec.type].render(spec, value)
                if value is not None
                else "—"
            )
            label = f"{spec.label}: {_short(shown)}"
            buttons.append([Button(label, EDIT_PREFIX + spec.key)])
        if session.form.submit_once:
            submit_label = session.form.labels.get("submit", "✔ Submit")
        else:
            submit_label = session.form.labels.get("submit", "✔ Submit & fill again")
        buttons.append(
            [Button(session.form.labels.get("cancel", "✖ Cancel"), CANCEL),
             Button(submit_label, SUBMIT)]
        )
        text = session.form.labels.get(
            "review_prompt",
            "Please review your answers (tap a field to edit):"
        )
        return Show(Prompt(text, buttons, {InputKind.BUTTON}))

    def _step_review(self, session: Session, inp: Input) -> Outcome:
        data = inp.button
        if data == CANCEL or inp.back:
            return Cancelled()
        if data == SUBMIT:
            return self._build_completed(session)
        if data and data.startswith(EDIT_PREFIX):
            key = data[len(EDIT_PREFIX):]
            try:
                session.cursor = session.form.field_index(key)
            except KeyError:
                return self._show_review(session)
            session.mode = "filling"
            session.return_to_review = True
            return self._ask_current(session)
        return self._show_review(session)

    def _build_completed(self, session: Session) -> Completed:
        record: dict[str, Any] = {}
        rendered: dict[str, str] = {}
        for spec in session.form.fields:
            if not self._visible(spec, session.answers):
                continue
            value = session.answers.get(spec.key)
            field_type = FIELD_TYPES[spec.type]
            if value is None:
                for column in field_type.columns(spec):
                    record[column] = None
            else:
                record.update(field_type.to_columns(spec, value))
            rendered[spec.label] = (
                field_type.render(spec, value) if value is not None else "—"
            )
        return Completed(
            record=record,
            rendered=rendered,
            restart=not session.form.submit_once,
        )

    def _visible(self, spec, answers: dict) -> bool:
        if spec.show_if is None:
            return True
        return answers.get(spec.show_if["key"]) == spec.show_if["value"]


def _short(text: object, limit: int = 24) -> str:
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Form loader
# ---------------------------------------------------------------------------

class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    title: str
    table: str | None = None
    kind: str = "form"
    query: str | None = None
    action: QueryAction | None = None
    context: list[ContextColumn] = []
    fields: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    submit_once: bool = False


def load_form(path: str | Path) -> FormSpec:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise FormError(f"Form file not found: {path}") from e
    except OSError as e:
        raise FormError(f"Could not read {path}: {e}") from e
    except yaml.YAMLError as e:
        raise FormError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(raw, dict):
        raise FormError(f"{path}: the top level must be a mapping")

    try:
        envelope = _Envelope.model_validate(raw)
    except ValidationError as e:
        raise FormError(f"{path}: {_first_error(e)}") from e

    if envelope.kind == "query":
        if not (envelope.query and envelope.query.strip()):
            raise FormError(f"{path}: a 'query' form needs a non-empty 'query'")
        fields: list[FieldSpec] = []
    elif envelope.kind == "form":
        if envelope.action is not None:
            raise FormError(f"{path}: 'action' is only for kind: query forms")
        fields = _load_fields(path, envelope.fields)
    else:
        raise FormError(f"{path}: unknown kind '{envelope.kind}' (form | query)")

    return FormSpec(
        name=envelope.name,
        title=envelope.title,
        table=envelope.table,
        fields=fields,
        context=list(envelope.context),
        kind=envelope.kind,
        query=envelope.query,
        action=envelope.action,
        labels=dict(envelope.labels),
        submit_once=envelope.submit_once,
    )


def _load_fields(path: Path, raw_fields: list[dict[str, Any]]) -> list[FieldSpec]:
    if not raw_fields:
        raise FormError(f"{path}: the form has no fields")

    specs: list[FieldSpec] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_fields):
        if not isinstance(raw, dict):
            raise FormError(f"{path}: field #{i} must be a mapping")
        key = raw.get("key", f"#{i}")
        ftype = raw.get("type")
        if not ftype:
            raise FormError(f"{path}: field '{key}' is missing 'type'")
        try:
            field_type = FIELD_TYPES[ftype]
        except KeyError:
            raise FormError(f"{path}: field '{key}': unknown field type '{ftype}'")
        try:
            spec = field_type.spec_model.model_validate(raw)
        except ValidationError as e:
            raise FormError(
                f"{path}: field '{key}' (type {ftype}): {_first_error(e)}"
            ) from e
        if spec.key in seen:
            raise FormError(f"{path}: duplicate field key '{spec.key}'")
        seen.add(spec.key)
        specs.append(spec)
    return specs


def _first_error(e: ValidationError) -> str:
    errors = e.errors()
    err = next((x for x in errors if x["type"] == "value_error"), errors[0])
    parts = [str(p) for p in err["loc"] if "[" not in str(p)]
    loc = ".".join(parts) or "(root)"
    msg = err["msg"].removeprefix("Value error, ")
    return f"{loc}: {msg}"


# ---------------------------------------------------------------------------
# Context resolver
# ---------------------------------------------------------------------------

def resolve_context(
    columns: list[ContextColumn], available: dict[str, Any]
) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for column in columns:
        if column.source not in available:
            raise ValueError(
                f"unknown context source '{column.source}' for column "
                f"'{column.column}' (known: {', '.join(sorted(available))})"
            )
        record[column.column] = available[column.source]
    return record


# ---------------------------------------------------------------------------
# Form resolution  (materialise dynamic select options)
# ---------------------------------------------------------------------------

def form_needs_db(form: FormSpec) -> bool:
    if form.kind == "query" or form.context:
        return True
    return any(
        isinstance(spec, SelectSpec) and spec.is_dynamic for spec in form.fields
    )


def resolve_form(form: FormSpec, catalog: Any | None) -> FormSpec:
    """Deep-copy *form*, query dynamic selects via *catalog*."""
    resolved = copy.deepcopy(form)
    for spec in resolved.fields:
        if isinstance(spec, SelectSpec) and spec.is_dynamic:
            if catalog is None:
                raise FormError(
                    f"select '{spec.key}' loads options from the database, "
                    f"but no database is configured"
                )
            spec.set_choices(catalog.options(spec.options))
    return resolved
