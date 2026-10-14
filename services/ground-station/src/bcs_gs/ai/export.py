"""``ai_calls`` queries and the JSONL export (training and evaluation datasets, section 17)."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any

from bcs_gs.core.logging import mask_secrets
from bcs_gs.store.repo import Repo

# Every ai_calls column. There is no key-value column: only key_slot (1-3).
EXPORT_COLUMNS = (
    "id",
    "request_id",
    "at",
    "role",
    "tier",
    "provider",
    "model",
    "key_slot",
    "prompt_version",
    "schema_version",
    "input_hash",
    "cache_key",
    "inputs",
    "image_refs",
    "output",
    "valid",
    "latency_ms",
    "status",
    "error",
    "fallback_from",
    "cache_hit",
)


def calls_where(filters: Mapping[str, Any]) -> tuple[str, tuple[Any, ...]]:
    """WHERE clause for the I2 filters ``role``, ``tier``, ``status``, ``from`` and ``to`` (ISO times,
    inclusive). Unknown or empty filters are ignored."""
    clauses: list[str] = []
    params: list[Any] = []
    for col in ("role", "tier", "status"):
        if filters.get(col):
            clauses.append(f'"{col}" = ?')
            params.append(filters[col])
    if filters.get("from"):
        clauses.append('"at" >= ?')
        params.append(filters["from"])
    if filters.get("to"):
        clauses.append('"at" <= ?')
        params.append(filters["to"])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", tuple(params)


def query_calls(repo: Repo, filters: Mapping[str, Any], *, newest_first: bool = True) -> list[dict[str, Any]]:
    """``ai_calls`` rows (decoded) matching ``filters``; ``limit`` caps the count when given."""
    where, params = calls_where(filters)
    sql = "SELECT " + ", ".join(f'"{c}"' for c in EXPORT_COLUMNS) + " FROM ai_calls" + where
    sql += " ORDER BY at DESC, id DESC" if newest_first else " ORDER BY at, id"
    if filters.get("limit"):
        sql += " LIMIT ?"
        params = (*params, int(filters["limit"]))
    return repo.query(sql, params, table="ai_calls")


def export_jsonl(repo: Repo, filters: Mapping[str, Any]) -> Iterator[str]:
    """One JSON object per line (no trailing newline), oldest first, with inputs and outputs. Each
    line is masked against every registered secret as a last line of defence."""
    for row in query_calls(repo, filters, newest_first=False):
        yield mask_secrets(json.dumps(row, separators=(",", ":"), ensure_ascii=False, sort_keys=False))
