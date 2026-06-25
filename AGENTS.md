# AGENTS.md

Philippe — Telegram bot that fills DB records from `form.yaml` dialogs.

## Commands

```bash
uv sync                      # core deps (pydantic, pyyaml, python-dotenv) + pytest
uv sync --extra telegram     # + aiogram
uv sync --extra bot          # + aiogram + psycopg (run against Postgres)

uv run pytest                # all 54 tests (no DB or network needed)
uv run pytest -k back        # filter

uv run philippe validate --form examples/task.yaml
uv run philippe run --forms-dir examples   # needs token + DB for dynamic-select forms
```

**`uv sync` extras are NOT additive.** Each call replaces the previous extras. Use the combined `bot` extra to get everything.

## Current structure (ultra-flat, 6 files)

| File | Contents |
|------|----------|
| `core.py` | All domain: models, field types, engine, loader, context, `resolve_form`. Pure Python, no I/O. |
| `_db.py` | `connect()`, `SqlCatalog`, `SqlSink`, `LoggingSink` |
| `_telegram.py` | `Runner`, `build_dispatcher`, `run_bot`, keyboards, message translation |
| `cli.py` | CLI parser + config/secret resolution (merged from old `config.py`) |

No Protocols, no decorator registry, no `transcribe/`, no `state/`. Field types live in a single `FIELD_TYPES` dict in `core.py:487` — add a new field by writing a class and adding it to that dict. No `@register`.

## Database sink gotchas

- `SqlSink` casts every placeholder to its column type (`%s::task_period`). **Load-bearing**: psycopg sends Python `str` as `text`, which can't implicitly cast to an enum. Don't remove the casts.
- Connection is `autocommit=True`.
- `select` options: static list, structured `{table,value,label,where,order_by}`, or raw `{query: SQL}`. `where`/`order_by`/`query` are raw SQL from trusted form files — never user input.
- `kind: query` forms run SQL that must return a `label` column. With `action: {form, prefill}` each row becomes a button launching another form prefilled from the row.

## Testing

- DB tests use `FakeConn` / `FakeCursor` — no live Postgres.
- `date.to_record` returns a real `datetime.date` (psycopg adapts it); `repeat.to_columns` returns two columns.

## Telegram adapter specifics

- Button taps → `edit_text` (in place), text messages → new `answer`.
- Callback data is button **index** (adapter keeps a per-chat index→payload map) to dodge Telegram's 64-byte callback-data limit.
- Blocking psycopg calls run via `asyncio.to_thread`.
- Access control: `PHILIPPE_ALLOWED_IDS` env var (comma-separated Telegram ids); unset = open.

## Config

- `.env` (git-ignored) auto-loaded. Keys: `PHILIPPE_BOT_TOKEN`, `DATABASE_URL`, `PHILIPPE_ALLOWED_IDS`.
- Without `DATABASE_URL`, records are logged but forms with dynamic `select` options / context / `kind: query` refuse to start.
- Local DB: `cd db && docker compose up -d` (Postgres + pgweb on :8081).

## Docs (reference, not architecture)

- `docs/form-schema.md` — every `form.yaml` key and field type.
- `docs/database.md` — field→column mapping, type casts.
- `examples/` — `task.yaml`, `log.yaml`, `today.yaml`, `sleep.yaml`, `workout.yaml`, `emotion.yaml` (each with a `-log` variant).