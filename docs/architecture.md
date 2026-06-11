# Architecture & module layout

This document describes how the Python project is structured and why the
boundaries are where they are. The guiding rule:

> **The domain core — forms, field types, dialog engine — knows nothing about
> Telegram, YAML, or SQL.** Those are adapters plugged in at the edges.

This keeps the conversation logic pure and unit-testable (no bot token, no
network), and lets the [roadmap](../README.md#roadmap) items — generating forms
from a DB schema, persisting to SQL, voice-to-text — slot in as new adapters
behind existing interfaces instead of rewrites.

## Layering at a glance


Dependencies point **inward**: adapters depend on the domain, never the
reverse. The domain talks to the outside world only through small `Protocol`
interfaces (ports).

## Source tree

A `src/` layout, single installable package `philippe`:

```
philippe/
├── pyproject.toml
├── README.md
├── docs/
│   ├── form-schema.md
│   └── architecture.md            # this file
├── examples/
│   └── form.yaml
├── src/
│   └── philippe/
│       ├── __init__.py
│       ├── __main__.py            # `python -m philippe` → cli.main()
│       ├── cli.py                 # arg parsing: `philippe run --form ...`
│       ├── config.py              # Settings: token, form path, log level (env + args)
│       │
│       ├── forms/                 # ── form definition: parse + validate ──
│       │   ├── __init__.py
│       │   ├── models.py          #   FormSpec, FieldSpec (pydantic models)
│       │   ├── loader.py          #   yaml file → FormSpec, raises FormError
│       │   └── errors.py          #   FormError / FieldError with file context
│       │
│       ├── fields/                # ── the field-type catalogue (plugin core) ──
│       │   ├── __init__.py        #   registry: name → FieldType, @register
│       │   ├── base.py            #   FieldType ABC + Prompt/Input/Step/Answer
│       │   ├── title.py           #   title   (short text, voice-capable)
│       │   ├── text.py            #   text    (long text, voice-capable)
│       │   ├── number.py          #   number  (range + presets)
│       │   ├── boolean.py         #   bool    (yes/no)
│       │   ├── select.py          #   select  (options, default, allow_custom)
│       │   ├── date.py            #   date    (relative buttons + parsing)
│       │   ├── repeat.py          #   repeat  (one message: period + frequency rows)
│       │   └── attachment.py      #   photo / media / audio
│       │
│       ├── dialog/                # ── framework-agnostic conversation engine ──
│       │   ├── __init__.py
│       │   ├── engine.py          #   drives field order, Back, review, restart
│       │   ├── session.py         #   per-user state: answers, cursor, field sub-state
│       │   ├── review.py          #   on_submit: build review, edit-link routing
│       │   └── ports.py           #   Presenter protocol (how output leaves the core)
│       │
│       ├── state/                 # ── session storage (port + impls) ──
│       │   ├── __init__.py
│       │   ├── store.py           #   SessionStore protocol
│       │   └── memory.py          #   in-memory dict impl (MVP)
│       │
│       ├── telegram/              # ── Telegram driving adapter (aiogram) ──
│       │   ├── __init__.py
│       │   ├── bot.py             #   build bot + dispatcher, wire handlers
│       │   ├── handlers.py        #   /start, text, callback, media handlers
│       │   ├── keyboards.py       #   Prompt.buttons → inline/reply keyboard
│       │   └── render.py          #   Prompt → message text; Update → Input
│       │
│       ├── sink/                  # ── where a finished record goes (port + impls) ──
│       │   ├── __init__.py
│       │   ├── base.py            #   RecordSink protocol
│       │   ├── logging.py         #   log/echo the assembled record (no DB)
│       │   └── sql.py             #   INSERT one row; per-column type casts
│       │
│       ├── db/                    # ── database access (psycopg only in connection) ──
│       │   ├── __init__.py
│       │   ├── connection.py      #   connect(dsn) — the only psycopg import
│       │   ├── catalog.py         #   Catalog port + SqlCatalog (dynamic options)
│       │   ├── resolve.py         #   resolve_form: materialize dynamic selects
│       │   └── identifiers.py     #   safe SQL identifier quoting
│       │
│       ├── context.py             #   map a form's context columns ← message values
│       │
│       └── transcribe/            # ── roadmap: voice → text (port + impls) ──
│           ├── __init__.py
│           └── base.py            #   Transcriber protocol
└── tests/
    ├── fields/                    # one test module per field type
    ├── dialog/                    # engine: order, back, review, edit, restart
    └── forms/                     # loader + validation errors
```

## Module responsibilities

### `forms/` — what a form *is*

Turns a `form.yaml` file into validated, typed objects and nothing more.

- **`models.py`** — `FormSpec` (name, title, table, `fields`) and the base
  `FieldSpec` (`key`, `type`, `label`, `required`, `default`, `help`). Each
  field type may extend `FieldSpec` with its own keys (e.g. `NumberSpec` adds
  `min`/`max`/`presets`).
- **`loader.py`** — reads YAML, dispatches each raw field to the right spec
  model via the [field registry](#fields--the-extensible-core), and returns a
  fully-validated `FormSpec`. All failures raise `FormError` with the field key
  and file location so the operator gets an actionable message.

`forms/` depends on `fields/` only to look up each type's spec model. It has no
runtime/dialog logic.

### `fields/` — the extensible core

Each field type is **one self-contained module** implementing the `FieldType`
interface. This is the project's main extension point: adding a type = adding a
file and registering it; nothing else changes.

A field type owns four concerns:

1. **Spec** — the extra YAML keys it accepts (a `FieldSpec` subclass).
2. **Prompt** — what question + keyboard to show, given the spec.
3. **Input handling** — parse/validate an incoming `Input`, producing the next
   `Step` (re-ask, complete with a value, or hand control back).
4. **Formatting** — render the stored value for the review, and convert it to a
   record value for the sink.

```python
# fields/base.py  (sketch)
class FieldType(ABC):
    name: ClassVar[str]                       # the `type:` string in YAML
    spec_model: ClassVar[type[FieldSpec]] = FieldSpec

    def start(self, spec: FieldSpec, fstate: dict) -> Prompt:
        """First question for this field (fstate is the field's scratch space)."""

    def handle(self, spec: FieldSpec, fstate: dict, inp: Input) -> Step:
        """Consume one user input → Ask(prompt) | Done(value) | Reject(msg)."""

    def render(self, spec: FieldSpec, value) -> str:
        """Human-readable value for the on_submit review."""

    def to_record(self, spec: FieldSpec, value):
        """Value as it should be stored in the DB column."""
```

Key abstractions (all framework-agnostic dataclasses):

- **`Input`** — a normalized user action: `text`, tapped `button` payload,
  `voice`/`photo`/`document`/`audio` attachment, or `back`. The Telegram
  adapter produces these; the field type never sees an aiogram object.
- **`Prompt`** — `text` + `buttons` (rows of `Button(label, value)`) + `expect`
  (which input kinds are valid here). The **`Back` button is appended by the
  engine**, not by each field — that's why "Back is always at the bottom" lives
  in one place.
- **`Step`** — the result of `handle`: `Ask(prompt)` (re-prompt, e.g. next
  sub-step or a validation message), or `Done(value)` (field complete).

**Why fields carry their own `fstate`:** some fields collect more than one
value before they are done. `repeat` shows period and frequency as two button
rows in a single message, tracks the chosen value of each in `fstate`, and
completes once **both** are picked; `date` offers buttons but also accepts typed
input. The engine gives each field a private `fstate` dict in the session so a
field can accumulate its partial state without the engine knowing the details.

```python
# fields/repeat.py  (sketch: one message, two rows, complete when both chosen)
@register
class Repeat(FieldType):
    name = "repeat"

    def start(self, spec, fstate):
        return self._prompt(fstate)               # period row + ×N row, none marked

    def handle(self, spec, fstate, inp):
        token = (inp.button or inp.text or "").strip()
        if token in PERIOD_VALUES:                # tapped a period button
            fstate["period"] = token
        elif 1 <= _as_int(token) <= 365:          # tapped ×N or typed a number
            fstate["every"] = _as_int(token)
        else:
            return Ask(self._prompt(fstate, hint="Pick a period and ×N, or 1–365."))
        if "period" in fstate and "every" in fstate:
            return Done(Recurrence(fstate["period"], fstate["every"]))
        return Ask(self._prompt(fstate))          # re-render with the "• "-marked pick
```

Each tap returns an `Ask` carrying the re-rendered prompt. The **Telegram
adapter edits the message in place** for button-driven `Ask`s (it calls
`edit_text`, not `answer`), so picking a period and then a ×N updates the one
message rather than posting a new one for each tap. See
[the Telegram adapter](#telegram--the-driving-adapter).

The **registry** in `fields/__init__.py` maps `"repeat" → Repeat()` and powers
both the loader (which spec model to use) and the engine (which handler to
run).

### `dialog/` — the conversation engine

Pure state machine that drives one form to completion. **No Telegram, no
storage** — it receives an `Input` and a `Session`, and emits a `Prompt` (or a
final `Commit`) for a `Presenter` to render.

- **`session.py`** — `Session`: the form, `answers: dict[str, Any]`, a `cursor`
  (current field index), each field's `fstate`, and a `mode`
  (`FILLING` / `REVIEW`). Plus a `return_to_review` flag for edit-from-review.
- **`engine.py`** — the core loop:
  1. Ask the current field's `FieldType.start`/`handle`.
  2. On `Done(value)`, store it under the field `key`, advance the cursor.
  3. On `Back`, pop to the previous field (kept answers preserved).
  4. After the last field, switch to `REVIEW`.
- **review (in `engine.py`)** — builds one button per field labelled
  `<field label>: <short answer>` (the value rendered via the field's `render`,
  then shortened to one line). Each button is an **edit link** that sets the
  cursor back to that field with `return_to_review = True`; the **Cancel** /
  **Submit & fill again** row finishes. On submit the engine returns the record
  for the adapter's `RecordSink`, then restarts the session for the next entry.
- **`ports.py`** — the `Presenter` protocol: `show(prompt)` / `commit(record)`.
  The engine outputs through this; the Telegram adapter implements it. This is
  the seam that keeps the engine UI-agnostic.

### `state/` — session storage (port)

`SessionStore` protocol: `get(chat_id) -> Session | None`, `put(chat_id, s)`,
`drop(chat_id)`. MVP ships `memory.py` (a dict). A Redis/SQL impl can be added
later without touching the engine — useful for surviving restarts.

### `telegram/` — the driving adapter

The only module that imports the Telegram framework (aiogram). It is a thin
translator in both directions:

- **inbound** (`render.py`): an aiogram `Update` → a domain `Input`.
- **outbound** (`keyboards.py` + `render.py`): a domain `Prompt` → message text
  + inline keyboard (appending the `Back` button supplied by the engine).
- **`handlers.py`**: `/start` creates a session and runs the engine; every
  message/callback loads the session, feeds the `Input` to the engine, and
  renders the resulting `Prompt`. A `Prompt` produced by a **button tap is
  rendered with `edit_text`** (the existing message updates in place); one
  produced by a **text message or `/start` is a new `answer`**. This is what
  keeps `repeat`'s two taps on a single message instead of re-sending it.

Swapping to a different chat platform = a new sibling adapter, core untouched.

### `sink/` — where the record lands (port)

`RecordSink.save(form: FormSpec, record: dict) -> None`, where `record` is
**column-keyed** (built by the engine via each field's `to_columns`).
`logging.py` echoes it (no DB). `sql.py` INSERTs one row into `FormSpec.table`:
it discovers column types from `information_schema` (cached per table) and casts
each `%s` to its column type, which is what lets a `str` reach an enum column.
Values only ever travel as parameters.

### `db/` — database access

The only package that touches Postgres, and only `connection.py` imports
psycopg (lazily). `catalog.py` reads a dynamic `select`'s options; `resolve.py`
produces a per-dialog copy of the form with those options materialized so
**fields stay I/O-free** — they only ever see static `(label, value)` choices.
`SqlCatalog` and `SqlSink` take an injected connection, so both are unit-tested
with a fake (no live DB). The Telegram adapter runs these blocking calls off the
event loop with `asyncio.to_thread`.

### field → column mapping

`FieldType` exposes `column(spec)` / `columns(spec)` / `to_columns(spec, value)`.
The default writes one column (`spec.column or spec.key`). Two overrides matter:
`repeat` → two columns (`period`, `every`); a dynamic `select` stores the chosen
**value** (an id) into its `column:` (e.g. `task_id`) while showing the label.
Form-level `context` columns (filled from the message, via `context.py`) are
merged in by the adapter at submit time.

### `transcribe/` — voice to text (port, roadmap)

`Transcriber.transcribe(audio) -> str`. The `title`/`text` field types request
voice input via `Prompt.expect`; the Telegram adapter, if a `Transcriber` is
configured, converts a voice message into `Input.text` before it reaches the
field. No transcriber configured ⇒ those fields are type-only. The field types
never change.

### `cli.py` / `config.py` / `__main__.py` — composition root

The **only** place where concrete adapters are wired to the core. `cli.py`
parses `philippe run --form examples/form.yaml`, `config.py` builds `Settings`
from env + args, and the composition root instantiates:
`MemorySessionStore`, `LoggingSink`, the loaded `FormSpec`, and the Telegram
adapter — then starts polling. Changing an implementation is a one-line change
here; nothing in the domain moves.

## Data flow: one answered field

```
Telegram Update
      │  telegram/render.py
      ▼
   Input  ───────────────►  dialog/engine.py
                               │ looks up FieldType in fields registry
                               │ FieldType.handle(spec, fstate, Input)
                               ▼
                            Step
              ┌──────────────┼───────────────┐
           Ask(prompt)    Done(value)      (Back)
              │              │ store answer    │ cursor--
              │              │ cursor++        │
              ▼              ▼                 ▼
            next Prompt ◄── engine builds next field's start() ──┘
              │  (engine appends the Back button)
              ▼  dialog Presenter (telegram/handlers.py)
   telegram/keyboards.py + render.py → reply message
```

After the last field the engine enters `REVIEW`; on **Submit** it calls
`RecordSink.save(form, answers-as-record)` and restarts the session.

## Why these boundaries

- **Testability.** `dialog/` + `fields/` are pure: a test feeds a list of
  `Input`s and asserts on emitted `Prompt`s and the final record — no bot, no
  network, no DB.
- **The roadmap is additive.** Form-from-schema = a new producer of `FormSpec`.
  DB persistence = a new `RecordSink`. Voice = a `Transcriber` impl. Each is a
  new file behind an existing port, not a change to the engine.
- **One concept, one place.** "Back is always at the bottom" and "review runs
  last" live in the engine, not duplicated across nine field types — exactly
  the universal behaviour the [form schema](form-schema.md) promises.
- **Adding a field type is local.** New `type:`? Add `fields/<type>.py`,
  `@register` it, done. The loader, engine, and adapters pick it up through the
  registry.

## Suggested dependencies

| Concern | Library |
|---------|---------|
| Telegram | `aiogram` (async, modern) |
| Form models / validation | `pydantic` v2 |
| YAML parsing | `pyyaml` |
| CLI | `argparse` (stdlib) or `typer` |
| DB sink (roadmap) | `SQLAlchemy` |
| Tests | `pytest` |

## Implementation notes (MVP)

What the shipped MVP does, and two small deviations from the plan above:

- **The engine is synchronous and returns `Outcome` objects** (`Show` /
  `Completed` / `Cancelled`) instead of pushing to a `Presenter` port. The
  driving adapter loops over outcomes and does the async I/O. This keeps the
  core pure and trivially testable (feed `Input`s, assert on `Outcome`s) — the
  `dialog/ports.py` Presenter abstraction wasn't needed yet.
- **`on_submit` review logic lives in `dialog/engine.py`**, not a separate
  `dialog/review.py` — it is small enough that splitting it added no value.
- **Reserved button payloads** (`__back__`, `__skip__`, `__submit__`,
  `__cancel__`, `__edit__:<key>`) are defined in `dialog/engine.py`. The
  Telegram adapter never sends these as callback data directly — it sends the
  button's *index* and keeps an index→value map per chat, sidestepping
  Telegram's 64-byte callback-data limit.

Covered by `tests/` (18 tests): form loading & validation errors, field order,
Back navigation, Skip, range re-ask, the one-message `repeat`, edit-from-review,
cancel, and submit-then-restart.
