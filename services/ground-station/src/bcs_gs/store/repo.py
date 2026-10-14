"""Repository: typed row writes with same-transaction outbox append."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from bcs_protocol.timefmt import to_iso

from bcs_gs.store.db import Database
from bcs_gs.store.schema import LOCAL_TABLES, SYNCED_TABLES, TableSpec


def _spec(table: str) -> TableSpec:
    spec = SYNCED_TABLES.get(table) or LOCAL_TABLES.get(table)
    if spec is None:
        raise ValueError(f"unknown table: {table}")
    return spec


def _encode(spec: TableSpec, row: dict[str, Any]) -> dict[str, Any]:
    """Encode a row for SQLite. NaN and +/-Infinity are rejected (ValueError) before anything is
    written: Postgres JSON and the cloud mirror cannot take them, so they would poison the outbox."""
    out: dict[str, Any] = {}
    for col, val in row.items():
        typ = spec.columns.get(col)
        if typ is None:
            raise ValueError(f"unknown column {spec.name}.{col}")
        if val is None:
            out[col] = None
        elif typ == "json":
            try:
                out[col] = json.dumps(val, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            except ValueError:
                raise ValueError(f"{spec.name}.{col}: JSON value contains NaN or Infinity") from None
        elif typ == "bool":
            out[col] = 1 if val else 0
        else:
            if isinstance(val, float) and not math.isfinite(val):
                raise ValueError(f"{spec.name}.{col}: non-finite number (NaN or Infinity) is not allowed")
            out[col] = val
    return out


def _decode_value(typ: str, val: Any) -> Any:
    if val is None:
        return None
    if typ == "json":
        return json.loads(val)
    if typ == "bool":
        return bool(val)
    return val


def _decode(spec: TableSpec, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {k: _decode_value(spec.columns.get(k, "text"), row[k]) for k in row.keys()}  # noqa: SIM118


def _name_types() -> dict[str, str]:
    """Column name -> type, for names whose type is the same in every synced table."""
    seen: dict[str, set[str]] = {}
    for spec in SYNCED_TABLES.values():
        for col, typ in spec.columns.items():
            seen.setdefault(col, set()).add(typ)
    return {c: next(iter(t)) for c, t in seen.items() if len(t) == 1}


_NAME_TYPES = _name_types()


class Repo:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._local = threading.local()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run several writes (and their outbox appends) in ONE database transaction. Nested use joins
        the outer transaction; an exception rolls everything back."""
        if getattr(self._local, "conn", None) is not None:
            yield
            return
        with self.db.tx() as conn:
            self._local.conn = conn
            try:
                yield
            finally:
                self._local.conn = None

    # -- writes -----------------------------------------------------------------------------
    def upsert(self, table: str, row: dict[str, Any], *, sync: bool = True) -> None:
        """Insert or update. Refused (ValueError) for the insert-only tables (A5: ``ledger_records``,
        ``evidence_packs``), whose rows are written once with ``insert``."""
        if _spec(table).sync_op == "insert_ignore":
            raise ValueError(f"{table} is insert-only: use Repo.insert, never upsert")
        self._write(table, row, sync=sync, replace=True)

    def insert(self, table: str, row: dict[str, Any], *, sync: bool = True) -> None:
        self._write(table, row, sync=sync, replace=False)

    def _write(self, table: str, row: dict[str, Any], *, sync: bool, replace: bool) -> None:
        spec = _spec(table)
        enc = _encode(spec, row)
        missing = [c for c in spec.pk if c not in enc or enc[c] is None]
        if missing:
            raise ValueError(f"{table}: primary key columns missing: {missing}")
        cols = list(enc)
        sql = (
            f'INSERT INTO "{table}" ('
            + ", ".join(f'"{c}"' for c in cols)
            + ") VALUES ("
            + ", ".join("?" for _ in cols)
            + ")"
        )
        if replace:
            sets = [c for c in cols if c not in spec.pk]
            if sets:
                sql += (
                    " ON CONFLICT ("
                    + ", ".join(f'"{c}"' for c in spec.pk)
                    + ") DO UPDATE SET "
                    + ", ".join(f'"{c}" = excluded."{c}"' for c in sets)
                )
            else:
                sql += " ON CONFLICT DO NOTHING"
        with self.transaction():
            conn = self._local.conn
            conn.execute(sql, [enc[c] for c in cols])
            if sync and table in SYNCED_TABLES:
                self._enqueue(conn, table, spec, {c: row[c] for c in spec.pk}, {c: enc[c] for c in spec.pk})

    def _enqueue(
        self, conn: sqlite3.Connection, table: str, spec: TableSpec, pk: dict[str, Any], enc_pk: dict[str, Any]
    ) -> None:
        """Append the row's current stored state to the outbox (inside the caller's transaction)."""
        full = conn.execute(
            f'SELECT * FROM "{table}" WHERE ' + " AND ".join(f'"{c}" = ?' for c in spec.pk),
            [enc_pk[c] for c in spec.pk],
        ).fetchone()
        payload = _decode(spec, full)
        conn.execute(
            "INSERT INTO sync_outbox (table_name, op, pk, payload, enqueued_at) VALUES (?, ?, ?, ?, ?)",
            (
                table,
                spec.sync_op,
                json.dumps(pk, separators=(",", ":")),
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False),
                to_iso(self.db.clock.now()),
            ),
        )

    def update_if(
        self,
        table: str,
        pk: dict[str, Any],
        changes: dict[str, Any],
        expect: dict[str, Any],
        *,
        sync: bool = True,
    ) -> bool:
        """Set ``changes`` on the row only while it still holds the ``expect`` values, in one
        statement (a conditional UPDATE), and enqueue the stored row. Columns not named are never
        touched, so a concurrent write to them is not lost. False when the row is gone or differs."""
        spec = _spec(table)
        enc_pk, enc_changes, enc_expect = _encode(spec, pk), _encode(spec, changes), _encode(spec, expect)
        where = [*spec.pk, *expect]
        sql = (
            f'UPDATE "{table}" SET '
            + ", ".join(f'"{c}" = ?' for c in enc_changes)
            + " WHERE "
            + " AND ".join(f'"{c}" = ?' for c in where)
        )
        with self.transaction():
            conn = self._local.conn
            cur = conn.execute(sql, [*enc_changes.values(), *(enc_pk[c] for c in spec.pk), *enc_expect.values()])
            if cur.rowcount != 1:
                return False
            if sync and table in SYNCED_TABLES:
                self._enqueue(conn, table, spec, pk, enc_pk)
            return True

    # -- reads ------------------------------------------------------------------------------
    def get(self, table: str, pk: dict[str, Any]) -> dict[str, Any] | None:
        spec = _spec(table)
        if set(pk) != set(spec.pk):
            raise ValueError(f"{table}: pk must be exactly {spec.pk}")
        enc = _encode(spec, pk)
        conn = self.db.read()
        try:
            r = conn.execute(
                f'SELECT * FROM "{table}" WHERE ' + " AND ".join(f'"{c}" = ?' for c in spec.pk),
                [enc[c] for c in spec.pk],
            ).fetchone()
        finally:
            conn.close()
        return None if r is None else _decode(spec, r)

    def query(
        self, sql: str, params: tuple[Any, ...] = (), *, table: str | None = None
    ) -> list[dict[str, Any]]:
        """Run a read-only query. With ``table`` its column types decode JSON/bool; otherwise columns
        are decoded by name when the type is unambiguous across the synced tables."""
        spec = _spec(table) if table else None
        conn = self.db.read()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            d = {}
            for k in r.keys():  # noqa: SIM118
                typ = spec.columns.get(k) if spec else _NAME_TYPES.get(k)
                d[k] = _decode_value(typ or "text", r[k])
            out.append(d)
        return out
