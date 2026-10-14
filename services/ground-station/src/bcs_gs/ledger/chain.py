"""Pure hash-chain verification over stored ledger records (spec N13, I3)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from bcs_gs.ledger.canonical import GENESIS_PREV, canonical_json, record_hash

# The ledger_records display columns (H2): copies of the canonical content's fields. Verification checks
# that each equals its canonical field, so a direct edit of a column is a broken record too.
TEXT_COLUMNS = ("record_id", "type", "created_at", "site_id", "quantity_tco2e", "gross_tco2e", "method_note",
                "label", "projected_record_id")  # fmt: skip
JSON_COLUMNS = ("zone_ids", "period", "deductions", "evidence", "confidence")
DISPLAY_COLUMNS = TEXT_COLUMNS + JSON_COLUMNS


@dataclass(frozen=True)
class StoredRecord:
    chain_index: int
    canonical: str | bytes  # bytes: the stored value read as a BLOB, decoded strictly here
    hash: str
    previous_hash: str
    # display column -> stored value (str, bytes read as a BLOB, or None); only the given ones are checked
    columns: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChainVerification:
    intact: bool
    checked: int
    first_broken_index: int | None
    at: str | None


def _text(raw: str | bytes) -> str:
    return raw.decode("utf-8") if isinstance(raw, bytes) else raw  # strict: invalid UTF-8 raises


def _same_json(a: Any, b: Any) -> bool:
    def norm(x: Any) -> str:
        return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    return norm(a) == norm(b)


def _columns_ok(columns: Mapping[str, Any], content: dict[str, Any]) -> bool:
    for col, raw in columns.items():
        want = content.get(col)
        if raw is None:
            if want is not None:
                return False
            continue
        if col in JSON_COLUMNS:
            if not _same_json(json.loads(_text(raw)), want):
                return False
        elif _text(raw) != want:
            return False
    return True


def _record_ok(rec: StoredRecord, expected_prev: str) -> bool:
    """Every check of one record; any exception (bad UTF-8, deep nesting, lone surrogates...) is a failure."""
    try:
        text = _text(rec.canonical)
        content: Any = json.loads(text)
        if canonical_json(content) != text:
            return False
        if not isinstance(content, dict) or content.get("chain_index") != rec.chain_index:
            return False
        if content.get("previous_hash") != rec.previous_hash:
            return False
        if record_hash(text) != rec.hash:
            return False
        if rec.previous_hash != expected_prev:
            return False
        return _columns_ok(rec.columns, content)
    except Exception:  # noqa: BLE001 - a crafted row must report as broken, never crash verification
        return False


def _first_problem(records: list[StoredRecord]) -> tuple[int, int] | None:
    """Return (position, reported_index) of the first failing record, or None if the chain is intact.

    Index continuity failures report the expected index (the missing or misplaced one); every other
    failure reports the record's own chain_index.
    """
    for pos, rec in enumerate(records):
        if rec.chain_index != pos:
            return pos, pos
        expected_prev = GENESIS_PREV if pos == 0 else records[pos - 1].hash
        if not _record_ok(rec, expected_prev):
            return pos, rec.chain_index
    return None


def verify(records: list[StoredRecord], at: str | None = None) -> ChainVerification:
    """Verify a chain in index order.

    `at` is the verification timestamp (ISO) the caller supplies from its clock; it is echoed into
    the result so this function stays pure. `checked` counts the records that verified cleanly
    before the first failure, or every record when the chain is intact.
    """
    problem = _first_problem(records)
    if problem is None:
        return ChainVerification(intact=True, checked=len(records), first_broken_index=None, at=at)
    pos, reported = problem
    return ChainVerification(intact=False, checked=pos, first_broken_index=reported, at=at)
