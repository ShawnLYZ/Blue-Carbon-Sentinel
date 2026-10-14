"""Identifier generators (addendum F1)."""

from __future__ import annotations

import os
import secrets
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> str:
    """RFC 9562 UUIDv7: 48-bit Unix ms, version 7, variant 10, monotonic within a millisecond.

    The 12-bit ``rand_a`` field holds a counter (randomly seeded at each new millisecond, with
    headroom) so that successive calls are strictly increasing as strings.
    """
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms = ms
            _counter = secrets.randbits(11)  # leave headroom for increments
        else:
            _counter += 1
            if _counter > 0xFFF:  # counter exhausted: borrow the next millisecond
                _last_ms += 1
                _counter = secrets.randbits(11)
        ts, ctr = _last_ms, _counter
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ts & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= ctr << 64
    value |= 0b10 << 62
    value |= rand_b
    return str(uuid.UUID(int=value))


def ledger_record_id(year: int, seq: int) -> str:
    return f"BC-{year:04d}-{seq:05d}"


def node_id(prefix: str, n: int) -> str:
    return f"{prefix}-{n:02d}"


def boot_id() -> str:
    return secrets.token_hex(6)
