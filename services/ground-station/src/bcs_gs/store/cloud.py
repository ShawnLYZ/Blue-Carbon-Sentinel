"""Cloud targets (addendum M): Supabase, an in-memory fake and a null target.

All methods are synchronous and may block; the sync worker calls them through ``asyncio.to_thread``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Protocol

from bcs_gs.store.schema import SYNCED_TABLES


class CloudError(Exception):
    """A cloud call failed. The message never contains the service key or the project URL.

    ``permanent`` is True when the cloud understood and rejected the request (constraint violation,
    4xx other than auth, timeout or rate limit): retrying the same payload can never succeed.
    Network failures, 5xx, 429 and auth problems are transient.
    """

    def __init__(self, message: str = "", permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


# Only data-specific rejections are permanent: SQLSTATE class 22 (data exception) and 23 (integrity
# constraint violation). Schema-level errors (class 42 such as 42P01/42703, PGRST schema-cache codes)
# hit every row of an unmigrated or drifted cloud, so they are systemic: the queue must wait, never
# dead-letter. 4xx that say nothing about the row (auth, timeout, rate limit, not found) are transient too.
_PERMANENT_SQLSTATE_CLASSES = ("22", "23")
_TRANSIENT_HTTP = {401, 403, 404, 408, 429}


def is_permanent_rejection(exc: Exception) -> bool:
    """True when ``exc`` is a definite rejection by the cloud rather than a transient failure."""
    code = str(getattr(exc, "code", "") or "")
    if len(code) == 5 and code.isalnum() and code.upper() == code:
        return code.startswith(_PERMANENT_SQLSTATE_CLASSES)
    if code.isdigit() and len(code) == 3:
        status = int(code)
        return 400 <= status < 500 and status not in _TRANSIENT_HTTP
    return False


# A select filter: (column, op, value) with op "eq", "gte" or "in" (value a list).
Filter = tuple[str, str, Any]
SELECT_PAGE_MAX = 1000  # rows one select call returns at most (the Supabase API cap)


class CloudTarget(Protocol):
    enabled: bool

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: tuple[str, ...]) -> None: ...
    def insert_ignore(self, table: str, rows: list[dict[str, Any]], on_conflict: tuple[str, ...]) -> None: ...
    def upload(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...
    def remove(self, bucket: str, keys: list[str]) -> None: ...
    def probe(self, bucket: str) -> None: ...  # cheap reachability check; raises when unreachable
    def select(
        self,
        table: str,
        filters: list[Filter] | None = None,
        order: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...  # order: column names, a leading "-" sorts descending
    def download(self, bucket: str, key: str) -> bytes: ...


class SupabaseCloudTarget:
    enabled = True

    def __init__(self, url: str, service_key: str) -> None:
        self._url = url
        self._key = service_key
        self._client: Any = None

    def _c(self) -> Any:
        if self._client is None:
            from supabase import create_client  # lazy: never imported by default tests

            self._client = create_client(self._url, self._key)
        return self._client

    def _scrub(self, exc: Exception) -> CloudError:
        msg = f"{type(exc).__name__}: {exc}"
        for secret in (self._key, self._url):
            if secret:
                msg = msg.replace(secret, "[redacted]")
        return CloudError(msg[:300], permanent=is_permanent_rejection(exc))

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: tuple[str, ...]) -> None:
        try:
            self._c().table(table).upsert(rows, on_conflict=",".join(on_conflict)).execute()
        except Exception as exc:  # noqa: BLE001
            raise self._scrub(exc) from None

    def insert_ignore(self, table: str, rows: list[dict[str, Any]], on_conflict: tuple[str, ...]) -> None:
        try:
            self._c().table(table).upsert(
                rows, on_conflict=",".join(on_conflict), ignore_duplicates=True
            ).execute()
        except Exception as exc:  # noqa: BLE001
            raise self._scrub(exc) from None

    def upload(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        try:
            self._c().storage.from_(bucket).upload(
                key, data, {"content-type": content_type, "upsert": "true"}
            )
        except Exception as exc:  # noqa: BLE001
            raise self._scrub(exc) from None

    def remove(self, bucket: str, keys: list[str]) -> None:
        try:
            self._c().storage.from_(bucket).remove(keys)
        except Exception as exc:  # noqa: BLE001
            raise self._scrub(exc) from None

    def probe(self, bucket: str) -> None:
        """Reachability of Storage: fetch the bucket's metadata (one small request)."""
        try:
            self._c().storage.get_bucket(bucket)
        except Exception as exc:  # noqa: BLE001
            raise self._scrub(exc) from None


    def select(
        self,
        table: str,
        filters: list[Filter] | None = None,
        order: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Read with the service role. At most ``SELECT_PAGE_MAX`` rows per call: page with ``offset``."""
        n = min(limit if limit is not None else SELECT_PAGE_MAX, SELECT_PAGE_MAX)
        try:
            q = self._c().table(table).select("*")
            for col, op, val in filters or []:
                q = q.in_(col, val) if op == "in" else q.gte(col, val) if op == "gte" else q.eq(col, val)
            for col in order or []:
                q = q.order(col.lstrip("-"), desc=col.startswith("-"))
            return list(q.range(offset, offset + n - 1).execute().data or [])
        except Exception as exc:  # noqa: BLE001
            raise self._scrub(exc) from None

    def download(self, bucket: str, key: str) -> bytes:
        try:
            return bytes(self._c().storage.from_(bucket).download(key))
        except Exception as exc:  # noqa: BLE001
            raise self._scrub(exc) from None


class NullCloudTarget:
    """Cloud sync disabled: the worker leaves the outbox untouched and reports ``offline``."""

    enabled = False

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: tuple[str, ...]) -> None:
        raise CloudError("cloud sync is disabled")

    insert_ignore = upsert

    def upload(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        raise CloudError("cloud sync is disabled")

    def remove(self, bucket: str, keys: list[str]) -> None:
        return None

    def probe(self, bucket: str) -> None:
        raise CloudError("cloud sync is disabled")

    def select(
        self,
        table: str,
        filters: list[Filter] | None = None,
        order: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        raise CloudError("cloud sync is disabled")

    def download(self, bucket: str, key: str) -> bytes:
        raise CloudError("cloud sync is disabled")


@dataclass(frozen=True)
class Call:
    table: str
    rows: list[dict[str, Any]]


class FakeCloudTarget:
    """In-memory target for tests (and test mode)."""

    enabled = True

    def __init__(self, failing: bool = False) -> None:
        self.failing = failing
        self.fail_after_write = False
        self.tables: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {}
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.calls: list[Call] = []
        self.updates = 0
        self.shuffle_ties = False  # tests: select() orders rows tied on the sort key arbitrarily

    def reset(self) -> None:
        """Healthy and empty again (test reset)."""
        self.failing = False
        self.fail_after_write = False
        self.tables.clear()
        self.objects.clear()
        self.calls.clear()
        self.updates = 0

    def _check(self) -> None:
        if self.failing:
            raise CloudError("fake cloud unavailable")

    def _write(
        self, table: str, rows: list[dict[str, Any]], on_conflict: tuple[str, ...], *, ignore: bool
    ) -> None:
        self._check()
        store = self.tables.setdefault(table, {})
        if table == "calibrations":
            self._check_one_active(store, rows, on_conflict, ignore=ignore)
        for row in rows:
            pk = tuple(row[c] for c in on_conflict)
            if pk in store:
                if ignore:
                    continue
                self.updates += 1
            store[pk] = dict(row)
        self.calls.append(Call(table, [dict(r) for r in rows]))
        if self.fail_after_write:
            raise CloudError("fake cloud failed after write")

    @staticmethod
    def _check_one_active(
        store: dict[tuple[Any, ...], dict[str, Any]],
        rows: list[dict[str, Any]],
        on_conflict: tuple[str, ...],
        *,
        ignore: bool,
    ) -> None:
        """Like the cloud's unique index ``calibrations_one_active``: rows apply in order and a second
        active calibration rejects the whole statement (a permanent 23505), nothing written."""
        active = {pk for pk, r in store.items() if r.get("active")}
        for row in rows:
            pk = tuple(row[c] for c in on_conflict)
            if ignore and pk in store:
                continue
            if row.get("active"):
                active.add(pk)
            else:
                active.discard(pk)
            if len(active) > 1:
                raise CloudError("duplicate key value violates unique constraint (23505)", permanent=True)

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: tuple[str, ...]) -> None:
        self._write(table, rows, on_conflict, ignore=False)

    def insert_ignore(self, table: str, rows: list[dict[str, Any]], on_conflict: tuple[str, ...]) -> None:
        self._write(table, rows, on_conflict, ignore=True)

    def upload(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self._check()
        self.objects[(bucket, key)] = (data, content_type)
        if self.fail_after_write:
            raise CloudError("fake cloud failed after write")

    def probe(self, bucket: str) -> None:
        self._check()

    def remove(self, bucket: str, keys: list[str]) -> None:
        self._check()
        for k in keys:
            self.objects.pop((bucket, k), None)

    def select(
        self,
        table: str,
        filters: list[Filter] | None = None,
        order: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self._check()
        rows = [dict(r) for r in self.tables.get(table, {}).values()]
        if self.shuffle_ties:  # tied rows come back in an order that varies per page, like an unordered query
            random.Random(offset).shuffle(rows)
        for col, op, val in filters or []:
            if op == "in":
                rows = [r for r in rows if r.get(col) in val]
            elif op == "gte":
                rows = [r for r in rows if r.get(col) is not None and r[col] >= val]
            else:
                rows = [r for r in rows if r.get(col) == val]
        for col in reversed(order or []):  # stable sorts, last key first
            name = col.lstrip("-")
            rows.sort(key=lambda r: r.get(name), reverse=col.startswith("-"))
        n = min(limit if limit is not None else SELECT_PAGE_MAX, SELECT_PAGE_MAX)
        return rows[offset : offset + n]

    def download(self, bucket: str, key: str) -> bytes:
        self._check()
        try:
            return self.objects[(bucket, key)][0]
        except KeyError:
            raise CloudError(f"no object {bucket}/{key}", permanent=True) from None

    def tables_in_order(self, table: str) -> list[dict[str, Any]]:
        return list(self.tables.get(table, {}).values())


def pk_columns(table: str) -> tuple[str, ...]:
    return SYNCED_TABLES[table].pk
