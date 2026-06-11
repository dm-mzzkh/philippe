"""The conversation engine: a pure, synchronous state machine.

It drives field order, the universal ``Back``/``Skip`` controls, the on_submit
review (with per-field edit links), and restart-after-submit. It performs no
I/O: feed it an :class:`Input` and a :class:`Session`, get back an
:class:`Outcome` for a driving adapter to render.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..fields import Ask, Button, Done, InputKind, Prompt, get_field_type
from ..fields.base import Input
from .session import Session

# Reserved button payloads. Field-supplied option values must not collide with
# these; they are namespaced with surrounding double underscores to avoid it.
BACK = "__back__"
SKIP = "__skip__"
SUBMIT = "__submit__"
CANCEL = "__cancel__"
EDIT_PREFIX = "__edit__:"


# --- outcomes the engine returns ------------------------------------------


@dataclass
class Show:
    """Render this prompt to the user and wait for the next input."""

    prompt: Prompt


@dataclass
class Completed:
    """The form was submitted. ``record`` is ready for the sink; ``rendered``
    is the human view used for the confirmation message."""

    record: dict[str, Any]
    rendered: dict[str, str]


@dataclass
class Cancelled:
    """The user cancelled the form."""


Outcome = Show | Completed | Cancelled


class Engine:
    def start(self, session: Session) -> Outcome:
        session.answers.clear()
        session.fstate.clear()
        session.cursor = 0
        session.mode = "filling"
        session.return_to_review = False
        return self._ask_current(session)

    def restart(self, session: Session) -> Outcome:
        """After a submit: begin the same form again for the next entry."""
        return self.start(session)

    def step(self, session: Session, inp: Input) -> Outcome:
        if session.mode == "review":
            return self._step_review(session, inp)
        return self._step_filling(session, inp)

    # --- filling mode -----------------------------------------------------

    def _step_filling(self, session: Session, inp: Input) -> Outcome:
        spec = session.current

        if inp.back:
            return self._go_back(session)

        if inp.button == SKIP and not spec.required:
            return self._store_and_advance(session, None)

        field_type = get_field_type(spec.type)
        fstate = session.fstate.setdefault(spec.key, {})
        result = field_type.handle(spec, fstate, inp)
        if isinstance(result, Ask):
            return Show(self._decorate(result.prompt, session))
        assert isinstance(result, Done)
        return self._store_and_advance(session, result.value)

    def _store_and_advance(self, session: Session, value: Any) -> Outcome:
        session.answers[session.current.key] = value
        if session.return_to_review:
            session.return_to_review = False
            return self._show_review(session)
        session.cursor += 1
        if session.cursor >= len(session.form.fields):
            return self._show_review(session)
        return self._ask_current(session)

    def _go_back(self, session: Session) -> Outcome:
        if session.return_to_review:
            session.return_to_review = False
            return self._show_review(session)
        if session.cursor == 0:
            return self._ask_current(session)  # nowhere to go back to: re-ask
        session.cursor -= 1
        return self._ask_current(session)

    def _ask_current(self, session: Session) -> Outcome:
        spec = session.current
        field_type = get_field_type(spec.type)
        fstate = session.fstate[spec.key] = {}  # fresh scratch space on (re)entry
        prompt = field_type.start(spec, fstate)
        return Show(self._decorate(prompt, session))

    def _decorate(self, prompt: Prompt, session: Session) -> Prompt:
        """Append the universal control row: optional Skip, then Back."""
        row = []
        if not session.current.required:
            row.append(Button("Skip", SKIP))
        row.append(Button("◀ Back", BACK))
        prompt.buttons = prompt.buttons + [row]
        return prompt

    # --- review mode ------------------------------------------------------

    def _show_review(self, session: Session) -> Outcome:
        session.mode = "review"
        buttons = []
        for spec in session.form.fields:
            value = session.answers.get(spec.key)
            shown = (
                get_field_type(spec.type).render(spec, value)
                if value is not None
                else "—"
            )
            label = f"{spec.label}: {_short(shown)}"
            buttons.append([Button(label, EDIT_PREFIX + spec.key)])
        buttons.append(
            [Button("✖ Cancel", CANCEL), Button("✔ Submit & fill again", SUBMIT)]
        )
        text = "Please review your answers (tap a field to edit):"
        return Show(Prompt(text, buttons, {InputKind.BUTTON}))

    def _step_review(self, session: Session, inp: Input) -> Outcome:
        data = inp.button
        if data == CANCEL or inp.back:
            return Cancelled()
        if data == SUBMIT:
            return self._build_completed(session)
        if data and data.startswith(EDIT_PREFIX):
            key = data[len(EDIT_PREFIX):]
            try:
                session.cursor = session.form.field_index(key)
            except KeyError:
                return self._show_review(session)
            session.mode = "filling"
            session.return_to_review = True
            return self._ask_current(session)
        return self._show_review(session)  # unrecognized tap: re-show

    def _build_completed(self, session: Session) -> Completed:
        record: dict[str, Any] = {}
        rendered: dict[str, str] = {}
        for spec in session.form.fields:
            value = session.answers.get(spec.key)
            field_type = get_field_type(spec.type)
            record[spec.key] = (
                field_type.to_record(spec, value) if value is not None else None
            )
            rendered[spec.label] = (
                field_type.render(spec, value) if value is not None else "—"
            )
        return Completed(record=record, rendered=rendered)


def _short(text: object, limit: int = 24) -> str:
    """A one-line, length-bounded value for a review button label."""
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"
