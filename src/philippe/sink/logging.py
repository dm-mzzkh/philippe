"""MVP sink: log the assembled record. Persisting to a DB is on the roadmap."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..forms.models import FormSpec

logger = logging.getLogger("philippe.sink")


class LoggingSink:
    def save(self, form: FormSpec, record: dict[str, Any]) -> None:
        target = form.table or form.name
        logger.info("record for %s: %s", target, json.dumps(record, default=str,
                                                             ensure_ascii=False))
