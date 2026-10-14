"""Canonical JSON, quantity formatting and SHA-256 record hashing (spec N13)."""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

GENESIS_PREV = "0" * 64

_TCO2E = Decimal("0.001")
_FRAC = Decimal("0.0001")
_PCT = Decimal("0.01")


def _reject_non_canonical(value: Any) -> None:
    """Walk the content and refuse anything that is not a JSON-native canonical value.

    Floats are refused, and so are Decimal objects and every other type: quantities must be
    fixed-place strings produced by the fmt_* helpers, so no formatting choice is made here.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"canonical JSON keys must be str, got {type(key).__name__}")
            _reject_non_canonical(item)
        return
    if isinstance(value, list):
        for item in value:
            _reject_non_canonical(item)
        return
    raise TypeError(f"canonical JSON refuses {type(value).__name__}; pass a fixed-decimal string")


def canonical_json(content: dict[str, Any]) -> str:
    """Serialise content as sorted-key, whitespace-free UTF-8 JSON text (N13)."""
    _reject_non_canonical(content)
    return json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fixed(d: Decimal, step: Decimal) -> str:
    if not isinstance(d, Decimal):
        raise TypeError(f"expected Decimal, got {type(d).__name__}")
    q = d.quantize(step, rounding=ROUND_HALF_UP)
    if q == 0:
        q = abs(q)  # never emit "-0.000"
    return format(q, "f")


def fmt_tco2e(d: Decimal) -> str:
    """tCO2e as a decimal string with 3 dp (half-up rounding)."""
    return _fixed(d, _TCO2E)


def fmt_frac(d: Decimal) -> str:
    """Fraction or confidence as a decimal string with 4 dp (half-up rounding)."""
    return _fixed(d, _FRAC)


def fmt_pct(d: Decimal) -> str:
    """Percentage as a decimal string with 2 dp (half-up rounding)."""
    return _fixed(d, _PCT)


def record_hash(canonical: str) -> str:
    """Lowercase hex SHA-256 of the canonical text's UTF-8 bytes."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
