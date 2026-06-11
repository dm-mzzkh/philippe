# Database integration

How a `form.yaml` ends up as a row in Postgres, and how to run it.

The worked example is the **home-cleaning calendar** in [`db/`](../db): two
tables (`tasks`, `logs`) plus a `task_period` enum — see
[`db/initdb/home_cal.sql`](../db/initdb/home_cal.sql). The forms
[`examples/task.yaml`](../examples/task.yaml) and
[`examples/log.yaml`](../examples/log.yaml) write into them.

## Running with a database

```bash
# 1. Start Postgres (and pgweb on :8081) — from the db/ folder:
cd db && docker compose up -d

# 2. Install the bot with the DB + Telegram extras:
uv sync --extra db --extra telegram

# 3. Point the bot at the DB and your token (in .env, see .env.example):
#    DATABASE_URL=postgresql://bot:bot@localhost:5432/bot_dev
#    PHILIPPE_BOT_TOKEN=...
uv run philippe run --form examples/log.yaml
```

- With `DATABASE_URL` set, completed forms are **INSERT**ed into `table`.
- Without it, records are only logged — and a form that *needs* the DB (dynamic
  options or `context`) refuses to start with a clear message.
- `--database-url` overrides the env var; `--env-file` points at a non-default
  `.env`.

## How fields map to columns

The submitted answers become a column-keyed row. Most fields write one column
named after their `key` (or an explicit `column:`); two cases are special.

| Form field | Columns written | Notes |
|------------|-----------------|-------|
| `title` / `text` | `key` (or `column`) | the string |
| `bool` | `key` | a real boolean |
| `date` | `key` | a real `date` (not a string) |
| `number` | `key` | int/float |
| `select` | `column` (e.g. `task_id`) | stores the **value**, see below |
| `repeat` | `period` + `every` | one field → **two** columns |
| `context` entry | its `column` | filled from the message, not asked |

### `repeat` → `period` + `every`

A single `repeat` field fills two columns. They default to `period` and `every`
(matching the schema); rename with `period_column` / `every_column`:

```yaml
- key: schedule
  type: repeat
  label: How often?
  # period_column: period   # defaults
  # every_column: every
```

### `select` → a foreign key, options from the DB

A dynamic `select` shows a human label but stores a typed value (an id):

```yaml
- key: task
  type: select
  label: What did you do?
  column: task_id            # store the id in this FK column
  options:
    table: tasks
    value: id                # stored
    label: title             # shown on the button
    where: active = true     # raw SQL filter (trusted form file)
    order_by: title
```

Options are queried **once per dialog** when the user runs `/start`, so each
conversation sees the current set of (e.g. active) rows. The query lives in the
adapter, not the field — fields stay free of I/O; see
[`db/resolve.py`](../src/philippe/db/resolve.py).

### `context` — values from the message

Columns that aren't asked but come from the Telegram sender:

```yaml
context:
  - {column: user_id,   from: user_id}     # message.from_user.id
  - {column: user_name, from: user_name}   # "@" + username (or full name)
```

Available sources: `user_id`, `user_name`, `chat_id`.

## Type handling

The sink discovers each column's type from `information_schema` (once per table)
and casts every placeholder to it: `%s::task_period`, `%s::int4`, `%s::date`, …
This is what lets a plain Python `str` like `'week'` land in the `task_period`
**enum** column — psycopg sends `str` as `text`, and while there is no implicit
text→enum cast, the explicit `::task_period` cast is valid. Values always go
through parameters; only quoted identifiers and catalog-derived type names are
ever put into the SQL text.

## What is NOT done yet

- **No upsert / dedup.** `tasks.title` is `UNIQUE`; submitting a duplicate
  surfaces the database error to the user (the review stays open to retry/edit).
- **No editing existing rows** — every submit is an INSERT.
- A blocking psycopg call per submit/start is run off the event loop with
  `asyncio.to_thread`; there is no connection pool (fine for a home bot).
