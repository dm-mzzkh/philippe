# Philippe — a Telegram bot for filling database records

Philippe is a Telegram bot that helps people put data into a SQL database
**through guided dialogs instead of raw SQL**. Each database table is exposed
as a *form*: a sequence of typed fields the bot walks the user through, one
question at a time, validating input as it goes and writing a row at the end.

Forms can be **hand-written** (a `form.yaml` file) or **generated** from a
table's schema, then refined by hand.

## Why

Writing `INSERT` statements by hand is error-prone and unfriendly to
non-engineers. A Telegram dialog with buttons, voice input, presets and
validation lets anyone add a well-formed record from their phone, while the
form definition keeps the data consistent.

## Status

**MVP scope:** start the bot, point it at a single `form.yaml`, and let it
assemble the dialog from that file. Generating forms from a live table schema
and editing existing records come later — see [Roadmap](#roadmap).

## How a form works

A form is an ordered list of **fields**. The bot asks for each field in order
and stores the answer. Two rules hold for every field:

- **A `Back` button is always shown at the bottom**, returning to the previous
  field (answers already given are kept).
- The final step is always an **`on_submit` review**: the bot echoes everything
  entered as `parameter: value` pairs, where each value is a link that jumps
  back to re-edit that one field. From the review the user can **cancel** or
  **submit and start the same form again**.

Each field has a **type** that decides how the question is asked and how the
answer is validated. The full catalogue of types lives in
[docs/form-schema.md](docs/form-schema.md):

| Type | What the user does |
|------|--------------------|
| `title` | Short text — typed or sent as a voice message |
| `text` | Long text — typed or sent as a voice message |
| `repeat` | Pick a period (daily / weekly / monthly) and a frequency (1–365) |
| `bool` | Tap **Yes** / **No** |
| `date` | Tap a relative day, or type a weekday / `dd.mm` / `dd.mm.yyyy` |
| `number` | Type a number in a `[X, Y]` range, optionally via preset buttons |
| `select` | Tap one of several options; optionally type a custom value |
| `photo` / `media` / `audio` | Send a photo, file or audio message |
| `on_submit` | Review all answers, then cancel or submit |

## Quick start (uv)

> The bot is configured by a single form file. The MVP runs one form.

[`uv`](https://docs.astral.sh/uv/) creates the virtualenv and installs
dependencies on the first `uv run` — no manual setup. The Telegram adapter is
an optional extra:

```bash
uv sync                  # core deps + dev tools (pytest)
uv sync --extra telegram # also aiogram, needed for `run`
uv sync --extra bot      # aiogram + psycopg — run the bot against Postgres
```

> `uv sync` extras are **not additive** — each `uv sync` makes the environment
> match exactly the extras you pass. Install everything in one command (that's
> what the combined `bot` extra is for); running `--extra db` then
> `--extra telegram` would uninstall psycopg again.

Two commands (`uv run python -m philippe …` also works):

```bash
# Check a form loads and see its fields — no token needed:
uv run philippe validate --form examples/form.yaml

# Run the real Telegram bot (needs the token, see below).
# Offer several forms with repeated --form, or a whole directory:
uv run philippe run --form examples/task.yaml --form examples/log.yaml
uv run philippe run --forms-dir examples
```

In the bot, **`/forms`** (and `/start`) lists the forms to fill; tapping one
begins its dialog from the first field.

### Providing the bot token (`.env`)

`run` needs a Telegram token from [@BotFather](https://t.me/BotFather). Copy the
template and fill it in — the file is loaded automatically and is git-ignored:

```bash
cp .env.example .env
# edit .env → PHILIPPE_BOT_TOKEN=123456:ABC-...
uv run philippe run --form examples/form.yaml
```

Resolution order (first hit wins): `--token` flag → real environment variable →
`.env`. Point at a non-default file with `--env-file path/to/.env`, or let uv
load it: `uv run --env-file .env philippe run --form examples/form.yaml`.

### Writing to a database

The forms [`examples/task.yaml`](examples/task.yaml) and
[`examples/log.yaml`](examples/log.yaml) write into the Postgres schema in
[`db/`](db) (a home-cleaning calendar). Start the DB, set `DATABASE_URL`, and the
bot INSERTs each completed form as a row:

```bash
cd db && docker compose up -d         # Postgres on :5432, pgweb on :8081
# .env → DATABASE_URL=postgresql://bot:bot@localhost:5432/bot_dev
uv run philippe run --form examples/task.yaml --form examples/log.yaml
```

Without `DATABASE_URL` records are only logged. See
[docs/database.md](docs/database.md) for the field→column mapping (dynamic
`select` options, `repeat` → `period`+`every`, `context` columns, type casts).

### Tests

```bash
uv run pytest
```

## Project layout

```
.
├── README.md                # this file
├── docs/
│   ├── form-schema.md       # full form.yaml field reference
│   ├── architecture.md      # module structure & design rationale
│   └── database.md          # how forms map to DB rows; how to run with a DB
├── examples/                # form.yaml (showcase), task.yaml + log.yaml (DB)
├── db/                      # Postgres schema + docker-compose (home calendar)
└── src/philippe/            # the package (see docs/architecture.md)
    ├── forms/               # parse + validate form.yaml
    ├── fields/              # the field-type catalogue (plugin core)
    ├── dialog/              # framework-agnostic conversation engine
    ├── state/               # session storage (port + impls)
    ├── db/                  # connection, option catalog, per-dialog resolve
    ├── telegram/            # Telegram adapter (aiogram)
    ├── sink/                # where finished records go (logging + SQL)
    └── transcribe/          # voice → text (roadmap)
```

The core (`forms`, `fields`, `dialog`) has **no dependency on Telegram, YAML or
SQL** — those live in adapters at the edges. See
[docs/architecture.md](docs/architecture.md) for the full rationale.

## Roadmap

- [x] **MVP** — run the bot from a single `form.yaml` and collect one record.
- [x] Persist answers to Postgres (INSERT) — see [docs/database.md](docs/database.md).
- [ ] Generate a `form.yaml` from a table's schema.
- [ ] Edit existing records, not just insert new ones.
- [ ] Multiple forms / table picker in one bot.
- [ ] Voice-to-text for `title` / `text` fields.

## See also

- [docs/form-schema.md](docs/form-schema.md) — the form definition reference.
- [docs/architecture.md](docs/architecture.md) — module structure & design.
- [docs/database.md](docs/database.md) — mapping forms to DB rows; running with Postgres.
- [examples/form.yaml](examples/form.yaml) — a complete example form.
