"""The :class:`FieldType` interface and the framework-agnostic value types it
exchanges with the dialog engine.

Nothing here knows about Telegram, YAML, or SQL. A field type turns a
:class:`~philippe.forms.models.FieldSpec` into prompts, consumes normalized
:class:`Input`, and produces a stored value plus its human/record renderings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field as _field
from enum import Enum
from typing import Any, ClassVar

from ..forms.models import FieldSpec


class InputKind(str, Enum):
    """Kinds of user input a prompt may accept / an input may carry."""

    TEXT = "text"
    BUTTON = "button"
    VOICE = "voice"
    PHOTO = "photo"
    DOCUMENT = "document"
    AUDIO = "audio"


@dataclass(frozen=True)
class Button:
    """A tappable choice. ``value`` is the payload handed back as ``Input.button``."""

    label: str
    value: str


@dataclass(frozen=True)
class Attachment:
    """A normalized media attachment (Telegram file ids, kept opaque to the core)."""

    kind: InputKind
    file_id: str
    file_name: str | None = None


@dataclass
class Prompt:
    """A question to render: text, optional button rows, and accepted input kinds.

    The engine appends the universal ``Back`` (and ``Skip`` for optional fields)
    button row, so individual field types never build it themselves.
    """

    text: str
    buttons: list[list[Button]] = _field(default_factory=list)
    expect: set[InputKind] = _field(default_factory=lambda: {InputKind.TEXT})


@dataclass
class Input:
    """A normalized user action produced by a driving adapter (e.g. telegram)."""

    text: str | None = None
    button: str | None = None
    attachment: Attachment | None = None
    back: bool = False


# --- results of FieldType.handle ------------------------------------------


@dataclass
class Ask:
    """Re-prompt the user (next sub-step, or a validation message)."""

    prompt: Prompt


@dataclass
class Done:
    """The field is complete; ``value`` is stored under the field key."""

    value: Any


Step = Ask | Done


class FieldType(ABC):
    """Base class for every field type. Instances are stateless singletons;
    per-conversation scratch state lives in the ``fstate`` dict handed in."""

    name: ClassVar[str]
    spec_model: ClassVar[type[FieldSpec]] = FieldSpec

    @abstractmethod
    def start(self, spec: FieldSpec, fstate: dict) -> Prompt:
        """First question for this field. ``fstate`` starts empty."""

    @abstractmethod
    def handle(self, spec: FieldSpec, fstate: dict, inp: Input) -> Step:
        """Consume one input → ``Ask`` (re-prompt) or ``Done`` (value)."""

    def render(self, spec: FieldSpec, value: Any) -> str:
        """Human-readable value for the on_submit review."""
        return str(value)

    def to_record(self, spec: FieldSpec, value: Any) -> Any:
        """Value as it should be stored in the DB column."""
        return value

    # --- DB column mapping ------------------------------------------------
    # Most fields write one column named after the field key (or ``column:``).
    # A field type that fills several columns (e.g. ``repeat``) overrides
    # ``columns`` and ``to_columns`` together.

    def column(self, spec: FieldSpec) -> str:
        return spec.column or spec.key

    def columns(self, spec: FieldSpec) -> list[str]:
        """The DB columns this field writes (used to emit NULLs when skipped)."""
        return [self.column(spec)]

    def to_columns(self, spec: FieldSpec, value: Any) -> dict[str, Any]:
        """Map a (non-None) stored value to ``{column: db_value}``."""
        return {self.column(spec): self.to_record(spec, value)}
