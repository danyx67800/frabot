from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections import deque
from typing import Any

_SECRETS: set[str] = set()
_SECRETS_LOCK = threading.Lock()

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
    "message", "asctime",
}


def register_secrets(values: list[str]) -> None:
    with _SECRETS_LOCK:
        for value in values:
            if isinstance(value, str) and len(value) >= 6:
                _SECRETS.add(value)


class SecretFilter(logging.Filter):
    """Last line of defence: no configured token/secret can reach a log sink."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        with _SECRETS_LOCK:
            secrets = list(_SECRETS)
        for secret in secrets:
            if secret in message:
                message = message.replace(secret, "[REDACTED]")
        record.msg = message
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key.startswith("ctx_"):
                payload[key[4:]] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class LogBuffer(logging.Handler):
    def __init__(self, limit: int = 800) -> None:
        super().__init__()
        self.records: deque[dict[str, Any]] = deque(maxlen=limit)
        self._lock = threading.Lock()
        self.setFormatter(JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = json.loads(self.format(record))
        except Exception:  # logging must never break the app
            return
        with self._lock:
            self.records.append(entry)

    def snapshot(self, limit: int = 200, level: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            entries = list(self.records)
        if level:
            minimum = logging.getLevelName(level.upper())
            if isinstance(minimum, int):
                entries = [
                    e for e in entries
                    if logging.getLevelName(str(e.get("level", "INFO"))) >= minimum
                ]
        return list(reversed(entries[-limit:]))


def setup_logging(level: str = "INFO", buffer: LogBuffer | None = None) -> LogBuffer:
    buffer = buffer or LogBuffer()
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = JsonFormatter()
    scrubber = SecretFilter()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream.addFilter(scrubber)
    root.addHandler(stream)

    buffer.setFormatter(formatter)
    buffer.addFilter(scrubber)
    root.addHandler(buffer)

    # Uvicorn installs its own handlers before importing the app; route them
    # through the same JSON sink so `docker logs` stays machine-readable.
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    # Keep the panel's log view focused on app events instead of every poll.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True

    logging.getLogger("discord").setLevel(logging.INFO)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    return buffer
