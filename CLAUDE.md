# CLAUDE.md

Guidance for working in this repo. Read this first; deep dives live in `docs/`.

## What this is

**Philippe** — a Telegram bot that fills database records through guided
`form.yaml` dialogs instead of raw SQL. Each form is an ordered list of typed
fields the bot walks the user through, validating input, then writing one row.
Forms can also be **read views** (`kind: query`) that list rows from a query.

Target schema lives in `db/` (a home-cleaning calendar: `tasks`, `logs`).

## Commands

This is a `uv` project, `src/` layout, package `philippe`.

```bash
uv sync                  # core (pydantic, pyyaml, python-dotenv) + pytest
uv sync --extra telegram # + aiogram (for `run`)
uv sync --extra bot      # + aiogram AND psycopg (run against Postgres)

uv run pytest                              # all tests (40, no DB/network needed)
uv run pytest tests/test_engine.py -k back # one file / filter

uv run philippe validate --form examples/task.yaml   # load + print a form, no token
uv run philippe run --forms-dir examples             # run the bot (needs token; DB for some forms)
uv run philippe run --form examples/task.yaml --form examples/log.yaml
```

> **`uv sync` extras are NOT additive.** Each `uv sync` makes the env match
> exactly the extras passed; `--extra db` then `--extra telegram` uninstalls
> psycopg. Use the combined `bot` extra, or pass both in one command.

### Config / secrets

- `.env` is auto-loaded (git-ignored). Keys: `PHILIPPE_BOT_TOKEN` (from
  @BotFather), `DATABASE_URL` (e.g. `postgresql://bot:bot@localhost:5432/bot_dev`).
- Token resolution: `--token` → real env var → `.env`. Same for `--database-url`
  → `$DATABASE_URL`. Without a DSN, records are only logged; forms that need a DB
  (dynamic options, context, or `kind: query`) refuse to start.
- The DB runs via Docker: `cd db && docker compose up -d` (Postgres + pgweb:8081).

## Architecture — hexagonal, dependencies point inward

The **domain core knows nothing about Telegram, YAML, or SQL.** Those are
adapters at the edges, reached only through small `Protocol` ports. This keeps
the core pure and unit-testable (feed `Input`s, assert on `Outcome`s).

```
adapters:  telegram/  sink/sql  db/  state/memory  forms/loader  cli   ← I/O, frameworks
ports:     SessionStore  RecordSink  Catalog  Transcriber                ← Protocols
domain:    forms.models  fields.*  dialog.engine  context                ← pure Python, no I/O
```

| Package | Role |
|---------|------|
| `forms/` | parse + validate `form.yaml` → typed `FormSpec` / `FieldSpec` |
| `fields/` | the field-type catalogue (one module per type) behind a registry |
| `dialog/` | the conversation engine — a pure, **synchronous** state machine |
| `state/` | per-chat session storage (port + in-memory impl) |
| `db/` | connection, option `Catalog`, per-dialog form resolution |
| `sink/` | where a finished record goes — `LoggingSink`, `SqlSink` |
| `telegram/` | the only package importing aiogram; thin Update↔Input translator |
| `context.py` | map a form's `context` columns ← message values |
| `cli.py` / `config.py` | composition root: wire concrete adapters to the core |

The engine returns **`Outcome`** objects (`Show` / `Completed` / `Cancelled`);
the adapter does the async I/O. There is no `Presenter` push-port — see
`docs/architecture.md` for this and other MVP simplifications.

## How the core works

- **Field type** (`fields/base.py::FieldType`): `start`/`handle` (prompt + parse
  one `Input` → `Ask`|`Done`), `render` (review text), and the column mapping
  `column`/`columns`/`to_columns`. Stateless singletons; per-field scratch lives
  in a `fstate` dict the engine hands in (used by multi-value fields like
  `repeat` and `date`).
- **Registry** (`fields/__init__.py`): `@register` adds a type; the loader picks
  its `spec_model`, the engine its handler. Adding a type = add a module +
  `@register`, nothing else changes.
- **Engine** (`dialog/engine.py`): drives field order, the universal `Back`/`Skip`
  row (appended by the engine, not fields), the `on_submit` review with per-field
  edit links, and restart-after-submit. Reserved button payloads
  (`__back__`, `__skip__`, `__submit__`, `__cancel__`, `__edit__:<key>`) live here.
- **Field → column mapping**: default writes one column (`spec.column or
  spec.key`). `repeat` → two columns (`period`, `every`); a dynamic `select`
  stores the chosen **value** (an id) into its `column:` while showing the label.
  Form-level `context` columns are merged by the adapter at submit.

## Telegram adapter specifics

- `/forms` (and `/start`) shows an inline menu of the offered forms; tapping one
  starts it. Multi-form is an **adapter concept** — the engine still drives one form.
- `/start` also pins a persistent reply keyboard (`FORMS_REPLY_KB`) with a single
  `📋 Forms` button above the user's keyboard; tapping it (text == `FORMS_BUTTON`)
  re-opens the menu. It's a separate chat-level keyboard from the dialog's inline
  buttons (a message can carry only one), so it's set once and persists.
- A `Prompt` from a **button tap** is rendered with `edit_text` (in place); from
  a **text message** it's a new `answer`. This is why `repeat`'s two taps stay on
  one message instead of re-sending it.
- Callback data is the button's **index** (the adapter keeps an index→payload map
  per chat), sidestepping Telegram's 64-byte callback-data limit.
- Blocking psycopg calls run off the event loop via `asyncio.to_thread`.

## Database specifics (read before touching `sink/sql.py`)

- `SqlSink` discovers column types from `information_schema` (cached per table)
  and casts every placeholder to its type: `%s::task_period`, `%s::int4`, …
  **This is load-bearing**: psycopg sends Python `str` as `text`, and there is
  *no implicit* text→enum cast, so `'week'` into the `task_period` enum needs the
  explicit `::task_period`. Don't remove the casts.
- Connection is `autocommit=True` (each INSERT commits; option SELECTs at /start
  don't leave idle-in-transaction).
- `select` options: static list, structured `{table,value,label,where,order_by}`,
  or raw `{query: <SQL>}` (returns `label`+`value`, or a single column).
  `where`/`order_by`/`query` are raw SQL from the trusted form file — never user
  input. Values always travel as parameters.
- `kind: query` forms run their SQL and list rows (SQL must return `label`).
  Read-only by default; with an `action: {form, prefill}` block each row becomes
  a button that launches another form pre-filled from the row (`prefill` maps
  target field key → row column). `Engine.start(session, prefill=…)` seeds those
  answers and skips them. Cross-form `action` refs are validated at load time
  (`cli._validate_actions`). See `examples/today.yaml` (tap a task → log it done).
- Access control: `PHILIPPE_ALLOWED_IDS` (comma-separated Telegram ids) →
  `build_dispatcher` adds an `F.from_user.id.in_(...)` filter; unset = open.

## Conventions & gotchas

- **Keep the core pure.** Fields and the engine never do I/O. DB access happens
  in adapters; dynamic select options are materialized once per dialog by
  `db/resolve.py::resolve_form` so fields only ever see static choices.
- **Tests use fakes, not a live DB.** `SqlSink`/`SqlCatalog` take an injected
  connection; `tests/test_db.py` passes a `FakeConn`. There is no live-Postgres
  test — verify DB-facing changes with the fakes and let a human run the real bot.
- Run the bot's async wiring against a fake `Message` (see how it's exercised) —
  `Runner` methods are awaitable and don't need a live Telegram.
- `date.to_record` returns a real `date` (psycopg adapts it); `repeat.to_columns`
  returns two columns. If you add a field whose value isn't a plain scalar,
  implement `to_columns`/`render`/`to_record` accordingly.
- pydantic v2 everywhere; `extra="forbid"` on specs so unknown YAML keys are
  rejected. `forms/loader.py::_first_error` prefers validator messages over
  generic union-branch noise — keep that when touching option unions.

## Where to read more

- `docs/form-schema.md` — every `form.yaml` key and field type (the reference).
- `docs/architecture.md` — module-by-module design + rationale.
- `docs/database.md` — field→column mapping, type casts, running with Postgres.
- `examples/` — `task.yaml`, `log.yaml` (DB forms), `today.yaml` (actionable
  view), `history.yaml` (read view), `form.yaml` (all field types, logging only).
