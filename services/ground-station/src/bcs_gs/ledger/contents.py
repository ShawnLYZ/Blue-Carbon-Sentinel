"""Reading ledger records by their hashed canonical content, never by the display columns (spec N13).

The display columns of ``ledger_records`` are copies made for queries and the cloud mirror; chain
verification checks them, but every decision (totals, idempotency, issuance) reads the canonical text.
``canonical`` is read as a BLOB and decoded strictly, so a row with invalid UTF-8 is skipped (chain
verification reports it) instead of failing the whole query.
"""

from __future__ import annotations

import json
from typing import Any

CANONICAL_BLOB = "CAST(canonical AS BLOB) AS canonical"


def parse_canonical(raw: str | bytes | None) -> dict[str, Any] | None:
    """The content of a stored canonical value, or None when it cannot be read as a JSON object."""
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        content = json.loads(text)
    except Exception:  # noqa: BLE001 - bad UTF-8, bad JSON, deep nesting: unreadable, chain reports it
        return None
    return content if isinstance(content, dict) else None


def canonical_text(raw: str | bytes | None) -> str:
    """The stored canonical value as text for display (undecodable bytes replaced)."""
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw


def stored_contents(repo: Any) -> list[tuple[int, dict[str, Any]]]:
    """(chain_index, content) of every readable record, in chain order. Blocking."""
    rows = repo.query(f"SELECT chain_index, {CANONICAL_BLOB} FROM ledger_records ORDER BY chain_index")
    out = []
    for r in rows:
        content = parse_canonical(r["canonical"])
        if content is not None:
            out.append((r["chain_index"], content))
    return out


def verified_key(content: dict[str, Any]) -> tuple[str, str] | None:
    """(plan_id, zone) of a Verified record's content: at most one Verified per pair across plan versions."""
    if content.get("type") != "verified":
        return None
    plan_id = (content.get("evidence") or {}).get("plan_id")
    zones = content.get("zone_ids") or []
    if not isinstance(plan_id, str) or not zones or not isinstance(zones[0], str):
        return None
    return plan_id, zones[0]
