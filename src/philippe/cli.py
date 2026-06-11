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
    _add_form_arg(p_run)
    p_run.add_argument("--token", help="bot token (else $PHILIPPE_BOT_TOKEN / .env)")
    p_run.add_argument("--env-file", type=Path, help="path to a .env file to load")
    p_run.add_argument("--log-level", default="INFO")

    return parser


def _load(form_path: Path):
    try:
        return load_form(form_path)
    except FormError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(2)


def cmd_validate(args) -> None:
    form = _load(args.form)
    print(f"OK: form '{form.name}' — {form.title}")
    print(f"  table: {form.table or '(none)'}")
    print(f"  fields ({len(form.fields)}):")
    for spec in form.fields:
        req = "" if spec.required else " (optional)"
        print(f"    - {spec.key}: {spec.type}{req} — {spec.label}")


def cmd_run(args) -> None:
    from .config import load_env, resolve_token

    if args.env_file:
        load_env(args.env_file)
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    form = _load(args.form)
    try:
        from .telegram.bot import run_bot
    except ImportError as e:
        print(f"error: the Telegram adapter needs aiogram installed "
              f"(`uv sync --extra telegram`): {e}", file=sys.stderr)
        raise SystemExit(1)

    run_bot(form, resolve_token(args.token))


_COMMANDS = {"validate": cmd_validate, "run": cmd_run}


def main(argv: list[str] | None = None) -> None:
    from .config import load_env

    load_env()  # pick up a .env from the current directory (or its parents)
    args = build_parser().parse_args(argv)
    _COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
