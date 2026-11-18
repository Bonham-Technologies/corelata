"""Structured JSON logs for long-running processes (the worker). Copied from Coglossa."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import TextIO

_FIELDS = ("run_id", "discovery_id", "stage", "state", "duration_ms")
_LOGGERS = ("corelata", "procrastinate")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in _FIELDS:
            if hasattr(record, name):
                data[name] = getattr(record, name)
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def configure_json_logging(
    level: int = logging.INFO, stream: TextIO | None = None
) -> logging.Handler:
    """Attach one JSON handler to the corelata and procrastinate loggers (the root logger is
    left alone). Idempotent: an earlier JSON handler is replaced. Returns the handler so the
    caller can detach it with remove_json_logging when it stops."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    for name in _LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers = [h for h in logger.handlers if not isinstance(h.formatter, JsonFormatter)]
        logger.addHandler(handler)
        logger.setLevel(level)
    return handler


def remove_json_logging(handler: logging.Handler) -> None:
    for name in _LOGGERS:
        logging.getLogger(name).removeHandler(handler)
