# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                      # core deps only (no aiogram, no psycopg)
uv sync --extra bot          # everything needed to run (aiogram + psycopg)
# NOTE: extras are NOT additive — always use `bot` to get both

uv run pytest                # all tests (no DB or network)
uv run pytest -k back        # filter by name

uv run philippe validate --form examples/task.yaml
uv run philippe run --forms-dir examples   # needs PHILIPPE_BOT_TOKEN + DATABASE_URL
```

Local DB: `cd db && docker compose up -d` (Postgres on 5432, pgweb on :8081).

## Architecture

The bot is 4 source files under `src/philippe/`. Nothing else.

```
form.yaml ──► core.py (load_form) ──► FormSpec + FieldSpec models
                                           │
                                    Engine.step() loop
                                    (pure state machine, no I/O)
                                           │
              ┌────────────────────────────┴────────────────────────┐
         _telegram.py                                           _db.py
     Runner (per-chat state)                        SqlSink / SqlCatalog
     aiogram dispatcher                             LoggingSink (no DB)
```

**`core.py`** — all domain logic, pure Python, no I/O:
- `load_form(path)` parses YAML into `FormSpec` (validated by pydantic)
- `Engine` drives the conversation: `Engine.step(input) → Ask | Done`
- `FieldType` ABC: two methods `start(spec, fstate) → Prompt` and `handle(spec, fstate, inp) → Step`
- `FIELD_TYPES: dict[str, FieldType]` at line 590 — **this is the registry**. Add a new field type by subclassing `FieldType` and adding one entry here. No decorator, no auto-discovery.

**`_telegram.py`** — aiogram adapter:
- `Runner` holds per-chat state (current `Engine`, callback index→payload map)
- Button callback data is stored as an **index** (not the payload) to stay within Telegram's 64-byte limit; `Runner` maps index→value per chat
- Button taps → `edit_text`; text messages → `answer` (new message)
- Blocking psycopg calls wrapped in `asyncio.to_thread`

**`_db.py`** — two sinks, one catalog:
- `SqlSink.save()` builds `INSERT` with `%s::coltype` casts for every column — **do not remove the casts**, psycopg sends Python `str` as `text` which won't implicitly cast to Postgres enums
- `SqlCatalog.options()` resolves dynamic `select` options at form-start time
- `LoggingSink` is the no-DB fallback (just logs the record dict)

**`cli.py`** — argparse + env resolution, wires everything together at startup.

## Data flow for a form submission

1. `load_form` validates YAML → `FormSpec` with typed `FieldSpec` list
2. `_telegram.py` creates an `Engine(form_spec)` per chat session
3. Each user message calls `engine.step(Input(...))` → returns `Ask` (show next prompt) or `Done` (record complete)
4. On `Done`, `SqlSink.save(form, record)` runs the INSERT; dynamic `select` specs get their choices from `SqlCatalog` before the form starts

## `show_if` and `submit_once`

- `show_if: {key: value}` — field is skipped unless another field in the same form equals that value; evaluated by the engine, not the adapter
- `submit_once: true` — engine checks via `SqlCatalog` if a record already exists for today; refuses to start if so

## Public API

`__init__.py` re-exports everything callers need. Before removing any symbol from `core.py`, `_db.py`, or `_telegram.py`, check `__init__.py` and `tests/` — it may be part of the public surface.

## Tests

`tests/test_core.py` — unit tests for field types and engine, no I/O.  
`tests/test_db.py` — uses `FakeConn`/`FakeCursor` stubs, no live Postgres.

To run a single test: `uv run pytest tests/test_core.py::test_name`
