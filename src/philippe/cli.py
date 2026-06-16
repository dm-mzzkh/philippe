"""Command-line entry point.

    philippe validate --form FORM       # load + check a form.yaml, print a summary
    philippe run      --form FORM       # run the Telegram bot (needs aiogram + token)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .forms import FormError, load_form


def _add_form_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--form", required=True, type=Path, help="path to a form.yaml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="philippe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="load and validate a form.yaml")
    _add_form_arg(p_validate)

    p_run = sub.add_parser("run", help="run the Telegram bot")
    p_run.add_argument("--form", action="append", dest="forms", metavar="PATH",
                       help="a form.yaml to offer (repeatable)")
    p_run.add_argument("--forms-dir", type=Path,
                       help="offer every *.yaml in this directory")
    p_run.add_argument("--token", help="bot token (else $PHILIPPE_BOT_TOKEN / .env)")
    p_run.add_argument("--database-url", help="Postgres DSN (else $DATABASE_URL / .env); "
                                              "without it records are only logged")
    p_run.add_argument("--allowed-ids", help="comma-separated Telegram ids allowed to use "
                                             "the bot (else $PHILIPPE_ALLOWED_IDS; open if unset)")
    p_run.add_argument("--env-file", type=Path, help="path to a .env file to load")
    p_run.add_argument("--log-level", default="INFO")

    return parser


def _load(form_path: Path):
    try:
        return load_form(form_path)
    except FormError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(2)


def _load_forms(paths, forms_dir: Path | None) -> dict:
    """Load all requested forms into a {name: FormSpec} dict (name-keyed so the
    /forms menu and form-selection can address them)."""
    files = [Path(p) for p in (paths or [])]
    if forms_dir is not None:
        if not forms_dir.is_dir():
            print(f"error: --forms-dir not found or not a directory: {forms_dir}",
                  file=sys.stderr)
            raise SystemExit(2)
        found = sorted(forms_dir.glob("*.yaml"))
        if not found:
            print(f"error: no *.yaml forms in {forms_dir}", file=sys.stderr)
            raise SystemExit(2)
        files += found
    if not files:
        print("error: no forms — pass --form PATH (repeatable) or --forms-dir DIR",
              file=sys.stderr)
        raise SystemExit(2)

    forms: dict = {}
    for path in files:
        form = _load(path)
        if form.name in forms:
            print(f"error: two forms share the name '{form.name}' ({path})",
                  file=sys.stderr)
            raise SystemExit(2)
        forms[form.name] = form
    _validate_actions(forms)
    return forms


def _validate_actions(forms: dict) -> None:
    """A query view's `action` must point at a loaded form and prefill real fields."""
    for form in forms.values():
        if form.action is None:
            continue
        target = forms.get(form.action.form)
        if target is None:
            print(f"error: form '{form.name}': action.form '{form.action.form}' "
                  f"is not one of the loaded forms", file=sys.stderr)
            raise SystemExit(2)
        keys = {f.key for f in target.fields}
        for field_key in form.action.prefill:
            if field_key not in keys:
                print(f"error: form '{form.name}': action prefills '{field_key}', "
                      f"which is not a field of '{target.name}'", file=sys.stderr)
                raise SystemExit(2)


def cmd_validate(args) -> None:
    form = _load(args.form)
    print(f"OK: form '{form.name}' — {form.title}")
    if form.kind == "query":
        print("  kind: query (read-only view)")
        print(f"  query: {form.query.strip().splitlines()[0]} …")
        return
    print(f"  table: {form.table or '(none)'}")
    print(f"  fields ({len(form.fields)}):")
    for spec in form.fields:
        req = "" if spec.required else " (optional)"
        print(f"    - {spec.key}: {spec.type}{req} — {spec.label}")


def cmd_run(args) -> None:
    from .config import (
        load_env,
        resolve_allowed_ids,
        resolve_database_url,
        resolve_token,
    )

    if args.env_file:
        load_env(args.env_file)
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    forms = _load_forms(args.forms, args.forms_dir)
    try:
        from .telegram.bot import run_bot
    except ImportError as e:
        print(f"error: the Telegram adapter needs aiogram installed "
              f"(`uv sync --extra bot`): {e}", file=sys.stderr)
        raise SystemExit(1)

    sink, catalog = _build_db(forms.values(), resolve_database_url(args.database_url))
    run_bot(forms, resolve_token(args.token), sink=sink, catalog=catalog,
            allowed_ids=resolve_allowed_ids(args.allowed_ids))


def _build_db(forms, dsn: str | None):
    """Return (sink, catalog). With a DSN → SQL sink + catalog; without → the
    logging sink, warning about any forms that won't work until a DB is set."""
    from .db.resolve import form_needs_db

    if not dsn:
        needs_db = [f.name for f in forms if form_needs_db(f)]
        if needs_db:
            print(f"warning: forms {needs_db} need a database (dynamic options or "
                  f"context columns) and will fail to start until DATABASE_URL is set",
                  file=sys.stderr)
        from .sink import LoggingSink
        return LoggingSink(), None

    from .db.catalog import SqlCatalog
    from .db.connection import connect
    from .sink import SqlSink

    conn = connect(dsn)
    return SqlSink(conn), SqlCatalog(conn)


_COMMANDS = {"validate": cmd_validate, "run": cmd_run}


def main(argv: list[str] | None = None) -> None:
    from .config import load_env

    load_env()  # pick up a .env from the current directory (or its parents)
    args = build_parser().parse_args(argv)
    _COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
