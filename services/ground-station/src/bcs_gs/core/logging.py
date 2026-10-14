"""Logging setup. Secret values are masked; only key slot numbers should ever be logged."""

from __future__ import annotations

import logging
import os
import time

_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Mask this value in all log output from now on (ignores empty/very short values)."""
    if value and len(value) >= 6:
        _secrets.add(value)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if _secrets:
            msg = _mask(record.getMessage())
            record.msg, record.args = msg, None
            if record.exc_info and not record.exc_text:  # format now so the text can be masked
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = _mask(record.exc_text)
            if record.stack_info:
                record.stack_info = _mask(record.stack_info)
        return True


def _mask(text: str) -> str:
    for s in _secrets:
        text = text.replace(s, "***")
    return text


def mask_secrets(text: str) -> str:
    """``text`` with every registered secret value replaced by ``***`` (for text that is stored or
    published rather than logged, e.g. AI call errors)."""
    return _mask(text)


UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def redact_uvicorn_loggers() -> None:
    """Put the redaction filter on uvicorn's loggers (its handlers are its own, so the root handler's
    filter never sees its tracebacks). Idempotent; call again after uvicorn configures its logging."""
    for name in UVICORN_LOGGERS:
        lg = logging.getLogger(name)
        if not any(isinstance(f, RedactFilter) for f in lg.filters):
            lg.addFilter(RedactFilter())


def make_formatter() -> logging.Formatter:
    """UTC timestamps in the F2 shape, e.g. 2026-10-16T03:04:05.123Z."""
    f = logging.Formatter(
        "%(asctime)s.%(msecs)03dZ %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
    )
    f.converter = time.gmtime
    return f


def setup_logging(level: str | None = None) -> None:
    name = (level or os.environ.get("BCS_LOG_LEVEL") or "INFO").upper()
    root = logging.getLogger()
    root.setLevel(getattr(logging, name, logging.INFO))
    for noisy in ("httpx", "httpcore"):  # their INFO lines carry request URLs, which can carry keys
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not any(getattr(h, "_bcs", False) for h in root.handlers):
        h = logging.StreamHandler()
        h._bcs = True  # type: ignore[attr-defined]
        h.setFormatter(make_formatter())
        h.addFilter(RedactFilter())
        root.addHandler(h)
    redact_uvicorn_loggers()
