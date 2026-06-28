"""Command-line entry point.

    philippe validate --form FORM       # load + check a form.yaml, print a summary
    philippe run      --form FORM       # run the Telegram bot (needs aiogram + token)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .core import FormError, form_needs_db, load_form

TOKEN_ENV = "PHILIPPE_BOT_TOKEN"
DATABASE_ENV = "DATABASE_URL"
ALLOWED_ENV = "PHILIPPE_ALLOWED_IDS"
HYDRUS_URL_ENV = "HYDRUS_URL"
HYDRUS_KEY_ENV = "HYDRUS_KEY"


def load_env(path: str | Path | None = None) -> None:
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    dotenv_path = str(path) if path else find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)


def resolve_token(explicit: str | None) -> str:
    token = explicit or os.environ.get(TOKEN_ENV)
    if not token:
        raise SystemExit(
            f"No bot token. Pass --token or set {TOKEN_ENV} in the environment."
        )
    return token


def resolve_database_url(explicit: str | None) -> str | None:
    return explicit or os.environ.get(DATABASE_ENV)


def resolve_allowed_ids(explicit: str | None) -> set[int] | None:
    raw = explicit or os.environ.get(ALLOWED_ENV)
    if not raw:
        return None
    try:
        return {int(part) for part in raw.replace(" ", "").split(",") if part}
    except ValueError:
        raise SystemExit(f"{ALLOWED_ENV} must be comma-separated ids, e.g. 111,222")


def resolve_hydrus() -> tuple[str, str] | None:
    url = os.environ.get(HYDRUS_URL_ENV)
    key = os.environ.get(HYDRUS_KEY_ENV)
    if url and key:
        return url, key
    if url or key:
        raise SystemExit(
            f"Both {HYDRUS_URL_ENV} and {HYDRUS_KEY_ENV} must be set "
            f"(or neither)."
        )
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="philippe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="load and validate a form.yaml")
    p_validate.add_argument("--form", required=True, type=Path, help="path to a form.yaml")

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
    files = [Path(p) for p in (paths or [])]
    if forms_dir is not None:
        if not forms_dir.is_dir():
            print(f"error: --forms-dir not found or not a directory: {forms_dir}")
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
    for form in forms.values():
        if form.action is None:
            continue
        if form.action.form is None:  # ponytail: show_images action, no form target
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
    if args.env_file:
        load_env(args.env_file)
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    forms = _load_forms(args.forms, args.forms_dir)
    try:
        from ._telegram import run_bot
    except ImportError as e:
        print(f"error: the Telegram adapter needs aiogram installed "
              f"(`uv sync --extra bot`): {e}", file=sys.stderr)
        raise SystemExit(1)

    sink, catalog = _build_db(forms.values(), resolve_database_url(args.database_url))
    hydrus_client = _build_hydrus()
    run_bot(forms, resolve_token(args.token), sink=sink, catalog=catalog,
            hydrus_client=hydrus_client,
            allowed_ids=resolve_allowed_ids(args.allowed_ids))


def _build_db(forms, dsn: str | None):
    from ._db import LoggingSink, SqlCatalog, SqlSink, connect

    if not dsn:
        needs_db = [f.name for f in forms if form_needs_db(f)]
        if needs_db:
            print(f"warning: forms {needs_db} need a database (dynamic options or "
                  f"context columns) and will fail to start until DATABASE_URL is set")
        return LoggingSink(), None

    conn = connect(dsn)
    return SqlSink(conn), SqlCatalog(conn)


def _build_hydrus():
    creds = resolve_hydrus()
    if creds is None:
        return None
    from ._hydrus import HydrusClient
    url, key = creds
    return HydrusClient(url, key)


_COMMANDS = {"validate": cmd_validate, "run": cmd_run}


def main(argv: list[str] | None = None) -> None:
    load_env()
    args = build_parser().parse_args(argv)
    _COMMANDS[args.command](args)


if __name__ == "__main__":
    main()