"""Per-dialog form resolution: materialize dynamic ``select`` options.

Fields stay pure (no DB access). Instead, when a dialog starts, the adapter
calls :func:`resolve_form` to produce a copy of the form whose dynamic selects
have their ``(label, value)`` choices filled in from the catalog. The copy is
private to that one conversation, so concurrent dialogs see independent (and
freshly-queried) option lists.
"""

from __future__ import annotations

import copy

from ..fields.select import SelectSpec
from ..forms.errors import FormError
from ..forms.models import FormSpec
from .catalog import Catalog


def form_needs_db(form: FormSpec) -> bool:
    """True if the form can only work with a database (dynamic options or
    context columns)."""
    if form.context:
        return True
    return any(
        isinstance(spec, SelectSpec) and spec.is_dynamic for spec in form.fields
    )


def resolve_form(form: FormSpec, catalog: Catalog | None) -> FormSpec:
    resolved = copy.deepcopy(form)
    for spec in resolved.fields:
        if isinstance(spec, SelectSpec) and spec.is_dynamic:
            if catalog is None:
                raise FormError(
                    f"select '{spec.key}' loads options from the database, "
                    f"but no database is configured"
                )
            spec.set_choices(catalog.options(spec.options))
    return resolved
