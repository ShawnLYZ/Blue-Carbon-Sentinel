"""Ordered outbox drain to the cloud plus media upload (addendum H6)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from bcs_protocol.timefmt import from_iso, to_iso

from bcs_gs.core.clock import Clock
from bcs_gs.core.events import EventBus
from bcs_gs.store.cloud import CloudTarget, pk_columns
from bcs_gs.store.db import Database
from bcs_gs.store.media import MediaStore
from bcs_gs.store.outbox import Outbox
from bcs_gs.store.repo import Repo
from bcs_gs.store.retention import _capture_id

log = logging.getLogger("bcs_gs.sync")

BATCH_MAX = 500
MEDIA_BATCH = 20
OFFLINE_AFTER = 3
IDLE_POLL_S = 1.0
# A media object that keeps failing while Storage is evidently reachable (another upload succeeded in
# the same pass, or an explicit probe of the object's bucket succeeds; row success says nothing about
# Storage and does not count) is marked
# 'failed' after this many such failures: it stays on disk and is counted, but no longer blocks the
# queue nor counts as a failed pass. Failures without that evidence (an outage) never fail an object.
MEDIA_MAX_ATTEMPTS = 5
# The head outbox row that the cloud permanently rejects (a constraint violation or a non-auth 4xx;
# never a network error, 5xx or 429) this many times in a row is moved to sync_dead_letter so it
# cannot block the strictly ordered queue forever.
OUTBOX_MAX_PERMANENT_FAILURES = 5


def backoff_s(consecutive_failures: int) -> float:
    """1, 2, 4, ... capped at 60 s."""
    return float(min(60, 2 ** max(0, consecutive_failures - 1)))


@dataclass(frozen=True)
class DrainResult:
    rows: int
    media: int
    ok: bool


@dataclass(frozen=True)
class SyncStatus:
    state: str  # online | buffering | offline
    queue: int
    media_queue: int
    lag_s: float | None
    last_success_at: str | None
    media_failed: int = 0  # local only: not part of the sync.status event (J2)
    dead_letter: int = 0  # local only, as media_failed


def _err(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


class SyncWorker:
    def __init__(
        self,
        db: Database,
        media: MediaStore,
        cloud: CloudTarget,
        bus: EventBus,
        clock: Clock,
        on_offline: Callable[[bool], None],
        budget: Any | None = None,
    ) -> None:
        self.db = db
        self.media = media
        self.cloud = cloud
        self.bus = bus
        self.clock = clock
        self.on_offline = on_offline
        self.budget = budget
        self.outbox = Outbox(db)
        self._repo = Repo(db)
        self._failures = 0
        self._offline_raised = False
        self._last_success_at: str | None = None
        self._media_strikes: dict[tuple[str, str], int] = {}  # failures with reachability evidence
        self._published: tuple | None = None
        self._row_strikes: dict[int, int] = {}  # outbox seq -> consecutive permanent rejections

    def reset(self) -> None:
        """Forget failure, offline and success bookkeeping (test reset: the store was cleared)."""
        was_offline = self._offline_raised
        self._failures = 0
        self._offline_raised = False
        self._last_success_at = None
        self._media_strikes.clear()
        self._row_strikes.clear()
        self._published = None
        if was_offline:
            self.on_offline(False)

    # -- status -----------------------------------------------------------------------------
    @property
    def consecutive_failures(self) -> int:
        """Failed passes since the last good one (0 while healthy, even with rows still queued)."""
        return self._failures

    def status(self) -> SyncStatus:
        queue = self.outbox.count()
        counts = {
            r["state"]: int(r["n"])
            for r in self._repo.query(
                "SELECT state, COUNT(*) AS n FROM media_objects WHERE state IN ('pending', 'failed') "
                "GROUP BY state"
            )
        }
        media_queue = counts.get("pending", 0)
        lag: float | None = None
        head = self.outbox.pending(1) if queue else []  # the sync loop may drain the queue after the count
        if head:
            lag = max(0.0, (self.clock.now() - from_iso(head[0].enqueued_at)).total_seconds())
        if not self.cloud.enabled or self._failures >= OFFLINE_AFTER:
            state = "offline"  # disabled, or an outage: three consecutive failed passes (H6, cloud_offline)
        elif self._failures > 0 or queue > 0:
            state = "buffering"  # work not yet confirmed by the cloud is never "online"
        else:
            state = "online"
        return SyncStatus(
            state, queue, media_queue, lag, self._last_success_at, counts.get("failed", 0),
            self.outbox.dead_count(),
        )  # fmt: skip

    def _publish_if_changed(self) -> None:
        st = self.status()
        key = (st.state, st.queue, st.media_queue, st.last_success_at)
        if key != self._published:
            self._published = key
            data = asdict(st)
            data.pop("media_failed")
            data.pop("dead_letter")
            self.bus.publish("sync.status", data)

    # -- drain ------------------------------------------------------------------------------
    async def drain_once(self) -> DrainResult:
        if not self.cloud.enabled:
            self._publish_if_changed()
            return DrainResult(0, 0, True)
        (rows, _, row_error), (_, media, media_error, failed) = await asyncio.gather(
            self._drain_rows(), self._drain_media()
        )
        error = row_error
        if media_error is not None and failed is not None:
            if await self._media_object_failed(failed, media):
                media_error = None  # object-specific failure while the cloud is reachable
            error = error or media_error
        ok = error is None
        if ok:
            if rows or media or self._failures:
                self._last_success_at = to_iso(self.clock.now())
            self._failures = 0
            if self._offline_raised:
                self._offline_raised = False
                self.on_offline(False)
            if media and self.budget is not None:
                try:
                    await asyncio.to_thread(self.budget.enforce)
                except Exception as exc:  # noqa: BLE001
                    log.warning("media budget failed: %s", _err(exc))
        else:
            self._record_failure(error)
        self._publish_if_changed()
        return DrainResult(rows, media, ok)

    def _record_failure(self, error: str | None) -> None:
        """Shared failure accounting: consecutive count drives back-off and the offline signal."""
        self._failures += 1
        log.warning("cloud sync failed (%d consecutive): %s", self._failures, error)
        if self._failures >= OFFLINE_AFTER and not self._offline_raised:
            self._offline_raised = True
            self.on_offline(True)

    async def _drain_rows(self) -> tuple[int, int, str | None]:
        sent = 0
        while True:
            items = self.outbox.pending(BATCH_MAX)
            if not items:
                return sent, 0, None
            first = items[0]
            batch = []
            for it in items:
                if it.table_name != first.table_name or it.op != first.op:
                    break
                batch.append(it)
            try:
                await self._send(first.table_name, first.op, batch)
            except Exception as exc:  # noqa: BLE001
                permanent = bool(getattr(exc, "permanent", False))
                if permanent and len(batch) > 1:
                    # Which row the cloud rejects is unknown: isolate the head row and decide on it alone.
                    batch = batch[:1]
                    try:
                        await self._send(first.table_name, first.op, batch)
                    except Exception as exc2:  # noqa: BLE001
                        exc, permanent = exc2, bool(getattr(exc2, "permanent", False))
                    else:
                        self.outbox.ack([first.seq])
                        sent += 1
                        continue
                msg = _err(exc)
                seqs = [it.seq for it in batch]
                self.outbox.fail(seqs, msg)
                if not permanent:
                    return sent, 0, msg
                strikes = self._row_strikes.get(first.seq, 0) + 1
                self._row_strikes[first.seq] = strikes
                if strikes >= OUTBOX_MAX_PERMANENT_FAILURES:
                    self.outbox.dead_letter(first.seq, to_iso(self.clock.now()))
                    self._row_strikes.pop(first.seq, None)
                    # Row id and table only: the payload and the cloud message may carry row data.
                    log.warning(
                        "outbox row %d (%s) permanently rejected %d times; moved to dead letter",
                        first.seq, first.table_name, strikes,
                    )  # fmt: skip
                continue  # the head row was rejected, not the cloud: retry it or move on, no back-off
            seqs = [it.seq for it in batch]
            for it in batch:
                self._row_strikes.pop(it.seq, None)
            self.outbox.ack(seqs)
            sent += len(batch)

    async def _send(self, table: str, op: str, batch: list) -> None:
        pk = pk_columns(table)
        rows = [it.payload for it in batch]
        fn = self.cloud.insert_ignore if op == "insert_ignore" else self.cloud.upsert
        await asyncio.to_thread(fn, table, rows, pk)

    async def _reachable(self, bucket: str) -> bool:
        """One cheap explicit probe of the cloud (the object's storage bucket)."""
        probe = getattr(self.cloud, "probe", None)
        if probe is None:
            return False
        try:
            await asyncio.to_thread(probe, bucket)
        except Exception as exc:  # noqa: BLE001
            log.info("cloud probe failed: %s", type(exc).__name__)
            return False
        return True

    async def _media_object_failed(self, obj: tuple[str, str], uploaded: int) -> bool:
        """Account one media failure. True when Storage is evidently reachable (another upload
        succeeded in this pass, else an explicit probe of the bucket succeeds): then the failure is
        the object's own, and after MEDIA_MAX_ATTEMPTS such failures the object is marked 'failed'.
        Row success is not evidence (the database can be up while Storage is down). False (an
        outage) leaves the object pending and fails the pass."""
        evidence = uploaded > 0 or await self._reachable(obj[0])
        if not evidence:
            return False
        strikes = self._media_strikes.get(obj, 0) + 1
        self._media_strikes[obj] = strikes
        if strikes >= MEDIA_MAX_ATTEMPTS:
            self._set_media(obj[0], obj[1], "failed", None, keep_error=True)
            self._forget_media(obj)
            log.warning("media object %s/%s marked failed after %d attempts", obj[0], obj[1], strikes)
        return True

    def _forget_media(self, obj: tuple[str, str]) -> None:
        self._media_strikes.pop(obj, None)

    async def _drain_media(self) -> tuple[int, int, str | None, tuple[str, str] | None]:
        """Upload pending media, fewest attempts first (a repeatedly failing object sorts behind fresh
        ones). Stops at the first failure and returns it; ``drain_once`` decides what it means."""
        uploaded = 0
        while True:
            pending = self._repo.query(
                "SELECT bucket, key, content_type FROM media_objects WHERE state = 'pending' "
                "ORDER BY attempts, rowid LIMIT ?",
                (MEDIA_BATCH,),
            )
            if not pending:
                return 0, uploaded, None, None
            for obj in pending:
                bucket, key = obj["bucket"], obj["key"]
                try:
                    path = self.media.path(bucket, key)
                    if not path.exists():
                        self._set_media(bucket, key, "failed", "local file missing")
                        continue
                    await asyncio.to_thread(self._read_and_upload, path, bucket, key, obj["content_type"])
                except Exception as exc:  # noqa: BLE001
                    msg = _err(exc)
                    self._set_media(bucket, key, "pending", msg, attempt=True)
                    return 0, uploaded, msg, (bucket, key)
                self._set_media(bucket, key, "uploaded", None, uploaded_at=to_iso(self.clock.now()))
                self._forget_media((bucket, key))
                self._mark_capture_uploaded(bucket, key)
                uploaded += 1

    def _mark_capture_uploaded(self, bucket: str, key: str) -> None:
        """Once every media object of a capture is uploaded, record ``media_state = 'uploaded'`` on
        the capture (a synced row). Only a 'local' capture moves: 'pruned' is never overwritten."""
        if bucket != "captures":
            return
        cap_id = _capture_id(key)
        if not cap_id:
            return
        # One transaction: it holds the write lock, so the reads below see the latest committed state
        # and the conditional UPDATE only touches media_state (a concurrent baseline write to the same
        # capture row is never overwritten with a stale copy).
        with self._repo.transaction():
            row = self._repo.get("captures", {"id": cap_id})
            if row is None or row["media_state"] != "local":
                return
            keys = sorted(set((row.get("media") or {}).values()))
            if not keys or key not in keys:
                return
            marks = ", ".join("?" * len(keys))
            states = self._repo.query(
                f"SELECT state FROM media_objects WHERE bucket = ? AND key IN ({marks})", (bucket, *keys)
            )
            if len(states) == len(keys) and all(r["state"] == "uploaded" for r in states):
                self._repo.update_if(
                    "captures", {"id": cap_id}, {"media_state": "uploaded"}, {"media_state": "local"}
                )

    def _read_and_upload(self, path, bucket: str, key: str, content_type: str) -> None:
        self.cloud.upload(bucket, key, path.read_bytes(), content_type)

    def _set_media(
        self, bucket: str, key: str, state: str, error: str | None, *, uploaded_at: str | None = None,
        attempt: bool = False, keep_error: bool = False,
    ) -> None:  # fmt: skip
        error_sql = "COALESCE(?, last_error)" if keep_error else "?"
        with self.db.tx() as conn:
            conn.execute(
                f"UPDATE media_objects SET state = ?, last_error = {error_sql}, "
                "uploaded_at = COALESCE(?, uploaded_at), attempts = attempts + ? WHERE bucket = ? AND key = ?",
                (state, error, uploaded_at, 1 if attempt else 0, bucket, key),
            )

    # -- loop -------------------------------------------------------------------------------
    async def run(self) -> None:
        """Supervised loop: an unexpected error in one pass (e.g. a local DB fault) counts as a
        failed attempt and backs off; it never ends the task for the session."""
        while True:
            try:
                result = await self.drain_once()
                idle = result.ok and (
                    not self.cloud.enabled or (self.outbox.count() == 0 and self.status().media_queue == 0)
                )
                ok = result.ok
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                ok = idle = False
                kind = type(exc).__name__  # type only: messages may carry row data
                log.error("sync pass raised %s; counted as a failed attempt", kind)
                try:
                    self._record_failure(f"unexpected {kind}")
                    self._publish_if_changed()
                except Exception as inner:  # noqa: BLE001
                    log.error("sync failure accounting raised %s", type(inner).__name__)
            if not ok:
                await self.clock.sleep(backoff_s(self._failures))
            elif idle:
                await self.clock.sleep(IDLE_POLL_S)
            else:
                await asyncio.sleep(0)
