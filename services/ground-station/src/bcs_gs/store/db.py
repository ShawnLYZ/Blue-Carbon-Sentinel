"""SQLite connection management: one locked writer, a fresh connection per read."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from bcs_protocol.timefmt import to_iso

from bcs_gs.core.clock import Clock
from bcs_gs.store.schema import BOOTSTRAP_DDL, MIGRATIONS


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class Database:
    def __init__(self, path: Path, clock: Clock) -> None:
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._writer = _connect(self.path)

    def migrate(self) -> None:
        with self._lock:
            self._writer.execute(BOOTSTRAP_DDL)
            applied = {r["version"] for r in self._writer.execute("SELECT version FROM schema_migrations")}
            for version, script in enumerate(MIGRATIONS, start=1):
                if version in applied:
                    continue
                with self.tx() as conn:
                    for stmt in script.split(";\n"):
                        if stmt.strip():
                            conn.execute(stmt)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                        (version, to_iso(self.clock.now())),
                    )

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """The single writer connection inside one transaction (commit on success, else rollback)."""
        with self._lock:
            conn = self._writer
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def read(self) -> sqlite3.Connection:
        """A new connection per call; the caller closes it."""
        return _connect(self.path)

    def close(self) -> None:
        with self._lock:
            self._writer.close()
