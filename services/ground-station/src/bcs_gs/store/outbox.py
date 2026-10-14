"""Read/ack side of the sync outbox (drained by the sync worker, Task 8)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from bcs_gs.store.db import Database


@dataclass(frozen=True)
class OutboxItem:
    seq: int
    table_name: str
    op: str
    pk: dict[str, Any]
    payload: dict[str, Any]
    enqueued_at: str
    attempts: int
    last_error: str | None


class Outbox:
    def __init__(self, db: Database) -> None:
        self.db = db

    def pending(self, limit: int) -> list[OutboxItem]:
        conn = self.db.read()
        try:
            rows = conn.execute("SELECT * FROM sync_outbox ORDER BY seq LIMIT ?", (limit,)).fetchall()
        finally:
            conn.close()
        return [
            OutboxItem(
                seq=r["seq"],
                table_name=r["table_name"],
                op=r["op"],
                pk=json.loads(r["pk"]),
                payload=json.loads(r["payload"]),
                enqueued_at=r["enqueued_at"],
                attempts=r["attempts"],
                last_error=r["last_error"],
            )
            for r in rows
        ]

    def ack(self, seqs: list[int]) -> None:
        if not seqs:
            return
        with self.db.tx() as conn:
            conn.executemany("DELETE FROM sync_outbox WHERE seq = ?", [(s,) for s in seqs])

    def fail(self, seqs: list[int], error: str) -> None:
        if not seqs:
            return
        with self.db.tx() as conn:
            conn.executemany(
                "UPDATE sync_outbox SET attempts = attempts + 1, last_error = ? WHERE seq = ?",
                [(error, s) for s in seqs],
            )

    def dead_letter(self, seq: int, dead_at: str) -> None:
        """Move one row out of the queue into ``sync_dead_letter`` (kept locally, never retried)."""
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO sync_dead_letter "
                "(seq, table_name, op, pk, payload, enqueued_at, attempts, last_error, dead_at) "
                "SELECT seq, table_name, op, pk, payload, enqueued_at, attempts, last_error, ? "
                "FROM sync_outbox WHERE seq = ?",
                (dead_at, seq),
            )
            conn.execute("DELETE FROM sync_outbox WHERE seq = ?", (seq,))

    def dead_count(self) -> int:
        conn = self.db.read()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM sync_dead_letter").fetchone()[0])
        finally:
            conn.close()

    def count(self) -> int:
        conn = self.db.read()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0])
        finally:
            conn.close()
