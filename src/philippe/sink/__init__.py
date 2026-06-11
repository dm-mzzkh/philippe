"""Where a completed record goes."""

from .base import RecordSink
from .logging import LoggingSink
from .sql import SqlSink

__all__ = ["LoggingSink", "RecordSink", "SqlSink"]
