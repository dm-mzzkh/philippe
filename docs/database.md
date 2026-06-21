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

# 2. Install the bot with aiogram + psycopg (one combined extra; `uv sync`
#    extras are not additive, so don't run them in separate commands):
uv sync --extra bot

# 3. Point the bot at the DB and your token (in .env, see .env.example):
#    DATABASE_URL=postgresql://bot:bot@localhost:5432/bot_dev
#    PHILIPPE_BOT_TOKEN=...
uv run philippe run --form examples/task.yaml --form examples/log.yaml
```

In the bot, `/forms` lists the offered forms; tap one to fill it.

- With `DATABASE_URL` set, completed forms are **INSERT**ed into `table`.
- Without it, records are only logged — and a form that *needs* the DB (dynamic
  options, `context`, or `kind: query`) refuses to start with a clear message.
- `--database-url` overrides the env var; `--env-file` points at a non-default
  `.env`.

### Loading / resetting the schema

`initdb/home_cal.sql` is mounted at `/docker-entrypoint-initdb.d`, but Postgres
runs init scripts **only on first initialization of an empty data directory**.
`docker compose restart` (or `up` without `down`) does *not* re-run it — so if
you see `relation "tasks" does not exist`, the schema simply isn't loaded.

`home_cal.sql` is idempotent (it drops and recreates everything), so reload it
into the running container at any time:

```bash
cd db
docker compose exec -T db psql -U bot -d bot_dev < initdb/home_cal.sql
docker compose exec db psql -U bot -d bot_dev -c '\dt'   # verify tasks/logs exist
```

Or recreate from scratch — note the `-v`, or the anonymous PGDATA volume sticks
around and init is skipped again:

```bash
docker compose down -v && docker compose up -d
```

### Deploying the full stack (bot + DB)

`db/docker-compose.yml` is for **local dev** — it publishes Postgres on `:5432`
and pgweb on `:8081` so a host-side `uv run philippe` can reach them.

The root [`compose.yml`](../compose.yml) is the **production** stack: it builds
the bot image ([`Dockerfile`](../Dockerfile)) and runs bot + Postgres + pgweb
together. Postgres is *not* published — the bot reaches it over the compose
network — and pgweb binds to `PGWEB_BIND` (default `127.0.0.1`; set it to the
host's Tailscale IP, see [`.env.example`](../.env.example)).

```bash
# .env needs PHILIPPE_BOT_TOKEN (+ optional PHILIPPE_ALLOWED_IDS, PGWEB_BIND).
# DATABASE_URL is set by compose.yml itself (db:5432), so .env's value is dev-only.
docker compose up -d --build          # uses the root compose.yml
```

`home_cal.sql` runs once when the named `pgdata` volume is first created; reload
it later with the `docker compose exec ... psql` command above.

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

Options are materialized **once per dialog** when the user runs `/start`, so each
conversation sees the current set of (e.g. active) rows. The query lives in the
adapter, not the field — fields stay free of I/O; see
[`db/resolve.py`](../src/philippe/db/resolve.py).

For anything the structured form can't express (DISTINCT, joins, aggregates),
use a raw `query` instead of `table/value/label`:

```yaml
- key: who
  type: select
  label: Who did it?
  column: user_name
  allow_custom: true
  options:
    query: SELECT DISTINCT user_name AS value, user_name AS label
           FROM logs WHERE user_name IS NOT NULL ORDER BY 1
```

The query must return `label` and `value` columns (or a single column, used for
both). It is raw SQL from the trusted form file, like `where`/`order_by`.

### `context` — values from the message

Columns that aren't asked but come from the Telegram sender:

```yaml
context:
  - {column: user_id,   from: user_id}     # message.from_user.id
  - {column: user_name, from: user_name}   # "@" + username (or full name)
```

Available sources: `user_id`, `user_name`, `chat_id`.

## Views (`kind: query`)

A form with `kind: query` runs its `query` and lists the rows (the SQL must
return a `label` column). It comes in two flavours:

- **read-only** (no `action`) — a plain text list, nothing written.
- **actionable** (with `action`) — each row is a button; tapping it launches
  another form pre-filled from that row.

[`examples/today.yaml`](../examples/today.yaml) lists tasks due today or overdue
(computed from `tasks` + the latest `logs.done_at`, `last_done + every×period`
via `make_interval`; `🆕` = never done, `🔴` = overdue), and is **actionable** —
tapping a task opens the `log` form with that task pre-filled, so the user just
confirms the date / adds a comment. This reproduces a "mark it done" loop while
staying fully generic.

```yaml
name: today
title: Сегодня нужно сделать
kind: query
action:
  form: log              # tap a row → start this form…
  prefill: {task: value} # …with field `task` set to the row's `value` column
query: |
  SELECT
    t.id AS value,                         -- fed into prefill
    '🆕 ' || t.title || ' — 🔴 N дн.' AS label   -- button text
  FROM tasks t ...
```

The prefilled field is skipped in the launched dialog; the user answers only the
remaining fields, then reviews and submits as usual.

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
