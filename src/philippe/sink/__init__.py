"""Where a completed record goes."""

from .base import RecordSink
from .logging import LoggingSink

__all__ = ["LoggingSink", "RecordSink"]
