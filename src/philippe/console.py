"""A terminal driving adapter — runs a ``form.yaml`` dialog over stdin/stdout.

This is the quickest way to see the MVP work end to end: no bot token, no
network, no aiogram. It renders prompts, lists buttons as numbered choices, and
turns typed lines into :class:`Input`. Reserved controls (Back/Skip/Cancel/…)
arrive as button payloads, exactly as they would from Telegram.
"""

from __future__ import annotations

from .dialog import Cancelled, Completed, Engine, Session, Show
from .dialog.engine import BACK
from .fields.base import Input, Prompt
from .forms.models import FormSpec
from .sink import LoggingSink
from .sink.base import RecordSink


def _render(prompt: Prompt) -> list[str]:
    """Print the prompt and return the ordered list of button payloads."""
    print("\n" + prompt.text)
    payloads: list[str] = []
    for row in prompt.buttons:
        for button in row:
            payloads.append(button.value)
            print(f"  [{len(payloads)}] {button.label}")
    return payloads


def _read_input(payloads: list[str]) -> Input:
    raw = input("> ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(payloads):
        value = payloads[int(raw) - 1]
        if value == BACK:
            return Input(back=True)
        return Input(button=value)
    return Input(text=raw)


def run_console(form: FormSpec, sink: RecordSink | None = None) -> None:
    sink = sink or LoggingSink()
    engine = Engine()
    session = Session(form=form)
    print(f"=== {form.title} ===  (type a number to pick a button, Ctrl-C to quit)")

    outcome = engine.start(session)
    while True:
        if isinstance(outcome, Show):
            payloads = _render(outcome.prompt)
            try:
                inp = _read_input(payloads)
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                return
            outcome = engine.step(session, inp)
        elif isinstance(outcome, Completed):
            print("\n✔ Submitted:")
            for label, value in outcome.rendered.items():
                print(f"   {label}: {value}")
            sink.save(form, outcome.record)
            print("\n— starting a new entry —")
            outcome = engine.restart(session)
        elif isinstance(outcome, Cancelled):
            print("\n✖ Cancelled.")
            return
