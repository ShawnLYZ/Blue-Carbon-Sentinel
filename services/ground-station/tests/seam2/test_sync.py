# ruff: noqa: UP031
import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from bcs_gs.core.clock import ManualClock
from bcs_gs.core.events import EventBus
from bcs_gs.store.cloud import CloudError, FakeCloudTarget, NullCloudTarget
from bcs_gs.store.db import Database
from bcs_gs.store.media import MediaStore
from bcs_gs.store.outbox import Outbox
from bcs_gs.store.repo import Repo
from bcs_gs.store.retention import MediaBudget, Retention
from bcs_gs.store.sync import SyncWorker, backoff_s
from bcs_protocol.timefmt import to_iso

T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)
TS = "2026-10-16T03:04:05.123Z"


def site(i):
    return {
        "id": i, "name": i, "status": "live", "region": "r", "centre_lat": 3.3, "centre_lng": 101.2,
        "anchor_nw_lat": None, "anchor_nw_lng": None, "bearing_deg": 0.0, "size_m": None,
        "scale_label": None, "rationale": "x", "updated_at": TS,
    }  # fmt: skip


def zone(i):
    return {
        "id": i, "site_id": "KSL", "label": i, "coordinate_id": i, "col": 1, "row": 1, "bounds": [],
        "bounds_site_m": [], "centre_lat": 3.3, "centre_lng": 101.2, "area_ha": 1.0,
    }  # fmt: skip


def alert_row(i):
    return {
        "id": f"0199aaaa-0000-7000-8000-00000000010{i}", "at": TS, "last_seen_at": TS, "occurrences": 1,
        "type": "node_offline", "severity": "warning", "zone_id": None, "node_id": None, "message": "m",
        "dedupe_key": f"k{i}", "details": {}, "acknowledged_at": None,
    }  # fmt: skip


LEDGER_ROW = {
    "chain_index": 0, "record_id": "BC-2026-00001", "type": "projected", "created_at": TS, "site_id": "KSL",
    "zone_ids": ["KSL-B3"], "period": {}, "quantity_tco2e": "1.250", "gross_tco2e": "1.500",
    "deductions": [], "evidence": [], "confidence": {}, "method_note": "n", "label": "Projected",
    "projected_record_id": None, "canonical": "{}", "previous_hash": "0" * 64, "hash": "a" * 64,
}  # fmt: skip


def ledger_row_citing(evidence):
    """A ledger row whose canonical content (what retention reads) and display column both carry ``evidence``."""
    return {**LEDGER_ROW, "evidence": evidence, "canonical": json.dumps({"evidence": evidence})}


def capture_row(cap_id, taken_at=TS, baseline=False, media_state="uploaded"):
    return {
        "id": cap_id, "taken_at": taken_at, "trigger": "interval", "imagery_source": "esp32cam",
        "bands": ["R", "G", "B"], "calibration_id": "cal", "frame_seq": 1, "media": {},
        "media_state": media_state, "quality": {}, "evidence_grade": False, "is_baseline": baseline,
        "flagged": False, "change_score": None, "retention_reason": None,
    }  # fmt: skip


def key_for(cap_id, name="image.jpg"):
    return f"2026/10/16/{cap_id}/{name}"


def media_keys(cap_id):
    return [key_for(cap_id), key_for(cap_id, "height.png")]


def seed_media(db, spec):
    repo = Repo(db)
    for n, (cap, size, protected) in enumerate(spec):
        repo.upsert("captures", capture_row(cap, baseline=protected), sync=False)
        for k in media_keys(cap):
            repo.upsert(
                "media_objects",
                {
                    "bucket": "captures", "key": k, "local_path": f"var/media/captures/{k}",
                    "content_type": "image/jpeg", "bytes": int(size // 2), "protected": protected,
                    "state": "uploaded", "uploaded_at": to_iso(T0 + timedelta(seconds=n)),
                    "attempts": 0, "last_error": None,
                },
                sync=False,
            )  # fmt: skip


def seed_captures(db, media, minute, count, baseline_index):
    repo = Repo(db)
    minute = minute.replace(second=0, microsecond=0)
    ids = []
    for i in range(count):
        cid = f"0199bbbb-0000-7000-8000-00000000000{i}"
        ids.append(cid)
        repo.upsert(
            "captures",
            capture_row(cid, to_iso(minute + timedelta(seconds=i)), baseline=i == baseline_index),
            sync=False,
        )
        media.put("captures", key_for(cid), b"x", "image/jpeg", cloud=False)
    return ids


def capture_row_db(db, cid):
    return Repo(db).get("captures", {"id": cid})


def remaining_capture_ids(db):
    return {r["id"] for r in Repo(db).query("select id from captures")}


@pytest.fixture
def clock():
    return ManualClock(T0)


@pytest.fixture
def db(tmp_path, clock):
    d = Database(tmp_path / "bcs.sqlite3", clock)
    d.migrate()
    yield d
    d.close()


@pytest.fixture
def media(tmp_path, db):
    return MediaStore(tmp_path, db)


@pytest.fixture
def fake_cloud():
    return FakeCloudTarget()


@pytest.fixture
def offline_calls():
    return []


@pytest.fixture
def world(db, media, clock, offline_calls):
    fake = FakeCloudTarget()
    bus = EventBus(clock)
    worker = SyncWorker(db, media, fake, bus, clock, on_offline=offline_calls.append)
    return Repo(db), worker, fake


async def test_drain_preserves_order_and_batches_consecutive_same_table(world):
    repo, worker, fake = world
    repo.upsert("sites", site("KSL"))
    repo.upsert("zones", zone("Z1"))
    repo.upsert("zones", zone("Z2"))
    repo.upsert("sites", site("B"))
    await worker.drain_once()
    assert [(c.table, len(c.rows)) for c in fake.calls] == [("sites", 1), ("zones", 2), ("sites", 1)]
    assert [r["id"] for r in fake.tables_in_order("sites")] == ["KSL", "B"]


async def test_failure_queues_then_recovers_without_duplicates(world, offline_calls):
    repo, worker, fake = world
    fake.failing = True
    for i in range(5):
        repo.upsert("alerts", alert_row(i))
    for _ in range(3):
        await worker.drain_once()
    assert worker.status().state == "offline" and worker.status().queue == 5  # 3 failures: H6 outage
    assert offline_calls == [True]
    fake.failing = False
    r = await worker.drain_once()
    assert r.ok and r.rows == 5
    assert worker.status().queue == 0 and len(fake.tables["alerts"]) == 5
    assert worker.status().state == "online" and offline_calls == [True, False]


async def test_state_is_offline_only_after_three_consecutive_failures(world, offline_calls):
    """Final review M7 (H6): "buffering" is unsent work or a recent failure; three consecutive failed passes
    are the outage ("offline", the state the top bar's badge is for). Recovery returns to online."""
    repo, worker, fake = world
    repo.upsert("sites", site("KSL"))
    assert worker.status().state == "buffering"  # queued, nothing failed yet
    fake.failing = True
    for n, want in ((1, "buffering"), (2, "buffering"), (3, "offline")):
        assert not (await worker.drain_once()).ok
        assert worker.status().state == want, n
    assert offline_calls == [True]
    fake.failing = False
    assert (await worker.drain_once()).ok and worker.status().state == "online"


async def test_ledger_insert_ignore_is_idempotent_on_retry(world):
    repo, worker, fake = world
    repo.insert("ledger_records", LEDGER_ROW)
    fake.fail_after_write = True
    await worker.drain_once()
    fake.fail_after_write = False
    await worker.drain_once()
    assert len(fake.tables["ledger_records"]) == 1 and fake.updates == 0


async def test_batches_cap_at_500_rows(world):
    repo, worker, fake = world
    with repo.db.tx() as conn:
        for i in range(501):
            payload = '{"component":"c%d","at":"%s","status":"ok","details":{}}' % (i, TS)
            conn.execute(
                "INSERT INTO sync_outbox (table_name, op, pk, payload, enqueued_at) VALUES (?,?,?,?,?)",
                ("system_heartbeats", "upsert", '{"component":"c%d"}' % i, payload, TS),
            )
    await worker.drain_once()
    assert [len(c.rows) for c in fake.calls] == [500, 1]


async def test_sync_status_published_on_change_with_lag(world, clock):
    repo, worker, _fake = world
    sub = worker.bus.subscribe()
    repo.upsert("sites", site("KSL"))
    clock.advance(7)
    assert worker.status().lag_s == 7 and worker.status().queue == 1
    await worker.drain_once()
    await worker.drain_once()  # no change -> no second event
    ev = list(sub._queue)
    assert [e.type for e in ev] == ["sync.status"]
    assert ev[0].data["state"] == "online" and ev[0].data["queue"] == 0
    assert ev[0].data["last_success_at"] == to_iso(clock.now())
    assert worker.status().lag_s is None


async def test_status_survives_the_queue_draining_while_it_is_read(world, monkeypatch):
    repo, worker, _fake = world
    repo.upsert("sites", site("KSL"))
    outbox, real_count = worker.outbox, worker.outbox.count

    def count_then_drain() -> int:
        n = real_count()
        outbox.ack([i.seq for i in outbox.pending(10)])  # the sync loop drains the row after the count
        return n

    monkeypatch.setattr(outbox, "count", count_then_drain)
    st = worker.status()
    assert st.queue == 1 and st.lag_s is None


async def test_media_upload_marks_uploaded_and_skips_local_only(world, media, db):
    repo, worker, fake = world
    media.put("captures", key_for("c1"), b"abc", "image/jpeg", cloud=True)
    media.put("captures", key_for("c2"), b"def", "image/jpeg", cloud=False)
    assert worker.status().media_queue == 1
    r = await worker.drain_once()
    assert r.media == 1 and fake.objects[("captures", key_for("c1"))] == (b"abc", "image/jpeg")
    assert ("captures", key_for("c2")) not in fake.objects
    states = {x["key"]: x["state"] for x in repo.query("select key, state from media_objects")}
    assert states == {key_for("c1"): "uploaded", key_for("c2"): "local_only"}


async def test_null_cloud_keeps_queue_and_reports_offline(db, media, clock):
    worker = SyncWorker(db, media, NullCloudTarget(), EventBus(clock), clock, on_offline=lambda _: None)
    Repo(db).upsert("sites", site("KSL"))
    r = await worker.drain_once()
    assert r.ok and r.rows == 0 and Outbox(db).count() == 1 and worker.status().state == "offline"


def test_backoff_is_exponential_capped_at_60():
    assert [backoff_s(n) for n in (1, 2, 3, 4, 7, 8, 20)] == [1, 2, 4, 8, 60, 60, 60]


async def test_run_backs_off_between_failures(world, clock, db):
    repo, worker, fake = world
    fake.failing = True
    repo.upsert("sites", site("KSL"))

    async def settle():
        await asyncio.sleep(0.05)

    def attempts():
        return Outbox(db).pending(1)[0].attempts

    task = asyncio.create_task(worker.run())
    try:
        await settle()
        assert attempts() == 1
        clock.advance(0.5)
        await settle()
        assert attempts() == 1
        clock.advance(0.5)
        await settle()
        assert attempts() == 2
        clock.advance(2)
        await settle()
        assert attempts() == 3
        fake.failing = False
        clock.advance(4)
        await settle()
        assert Outbox(db).count() == 0
    finally:
        task.cancel()


def test_budget_prunes_oldest_unprotected_capture_media_first(db, fake_cloud):
    seed_media(db, [("cap-1", 300e6, True), ("cap-2", 300e6, False), ("cap-3", 300e6, False)])
    for k in media_keys("cap-2"):
        fake_cloud.objects[("captures", k)] = (b"x", "image/jpeg")
    pruned = MediaBudget(db, fake_cloud, budget_bytes=800_000_000).enforce()
    assert sorted(k for _, k in pruned) == sorted(media_keys("cap-2"))
    assert capture_row_db(db, "cap-2")["media_state"] == "pruned"
    assert capture_row_db(db, "cap-1")["media_state"] == "uploaded"
    assert capture_row_db(db, "cap-3")["media_state"] == "uploaded"
    assert not any(k[1] in media_keys("cap-2") for k in fake_cloud.objects)
    # the pruned state is itself synced
    assert any(i.table_name == "captures" and i.pk == {"id": "cap-2"} for i in Outbox(db).pending(10))
    assert MediaBudget(db, fake_cloud, budget_bytes=800_000_000).enforce() == []


def test_budget_never_prunes_protected_even_when_over(db, fake_cloud):
    seed_media(db, [("cap-1", 300e6, True), ("cap-2", 300e6, True)])
    assert MediaBudget(db, fake_cloud, budget_bytes=100).enforce() == []


def test_budget_prunes_old_futures_after_captures(db, fake_cloud):
    repo = Repo(db)
    for i in range(4):
        repo.upsert(
            "forecasts",
            {
                "id": f"f{i}", "created_at": to_iso(T0 + timedelta(minutes=i)), "status": "ready",
                "plan_version_id": None, "base_capture_id": "c", "input_hash": "h", "parameters": {},
                "parameter_sources": {}, "keyframes": {}, "summary": {}, "bands": {},
            },
            sync=False,
        )  # fmt: skip
        repo.upsert(
            "media_objects",
            {
                "bucket": "futures", "key": f"f{i}/base/1/texture.jpg", "local_path": "p",
                "content_type": "image/jpeg", "bytes": 100, "protected": False, "state": "uploaded",
                "uploaded_at": to_iso(T0 + timedelta(minutes=i)), "attempts": 0, "last_error": None,
            },
            sync=False,
        )  # fmt: skip
    pruned = MediaBudget(db, fake_cloud, budget_bytes=1000).enforce()
    assert pruned == []
    pruned = MediaBudget(db, fake_cloud, budget_bytes=350).enforce()
    assert pruned == [("futures", "f0/base/1/texture.jpg")]


def test_budget_futures_latest_three_counts_ready_forecasts_only(db, fake_cloud):  # ruling R30 (#7)
    repo = Repo(db)
    statuses = ["ready", "ready", "ready", "failed", "pending"]  # f3, f4 newest but never ready
    for i, status in enumerate(statuses):
        repo.upsert(
            "forecasts",
            {
                "id": f"f{i}", "created_at": to_iso(T0 + timedelta(minutes=i)), "status": status,
                "plan_version_id": None, "base_capture_id": "c", "input_hash": "h", "parameters": {},
                "parameter_sources": {}, "keyframes": {}, "summary": {}, "bands": {},
            },
            sync=False,
        )  # fmt: skip
        if status != "ready":
            continue
        repo.upsert(
            "media_objects",
            {
                "bucket": "futures", "key": f"f{i}/base/1/texture.jpg", "local_path": "p",
                "content_type": "image/jpeg", "bytes": 100, "protected": False, "state": "uploaded",
                "uploaded_at": to_iso(T0 + timedelta(minutes=i)), "attempts": 0, "last_error": None,
            },
            sync=False,
        )  # fmt: skip
    # over budget: the three ready runs are still the latest three, so nothing of theirs is pruned
    assert MediaBudget(db, fake_cloud, budget_bytes=10).enforce() == []


def test_thinning_keeps_first_per_minute_and_protected(db, media, clock):
    ids = seed_captures(db, media, minute=clock.now() - timedelta(hours=25), count=6, baseline_index=3)
    Repo(db).upsert("zones", zone("Z"), sync=False)
    Repo(db).upsert(
        "zone_metrics",
        {
            "capture_id": ids[1], "zone_id": "Z", "canopy_pct": 1.0, "water_pct": 1.0, "mud_pct": 1.0,
            "other_pct": 1.0, "vari_mean": None, "vari_p10": None, "vari_p90": None,
            "canopy_loss_pp": None, "vari_drop": None, "dieback_pct": 0.0, "new_growth_pct": 0.0,
            "discolouration": None, "flags": [],
        },
        sync=False,
    )  # fmt: skip
    assert Retention(db, media, clock).thin_captures() == 4
    assert remaining_capture_ids(db) == {ids[0], ids[3]}
    assert not media.path("captures", key_for(ids[1])).exists()
    assert media.path("captures", key_for(ids[0])).exists()
    assert Repo(db).query("select 1 from zone_metrics") == []


def test_thinning_spares_recent_and_referenced_captures(db, media, clock):
    ids = seed_captures(db, media, minute=clock.now() - timedelta(hours=25), count=4, baseline_index=0)
    recent = seed_captures(db, media, minute=clock.now() - timedelta(hours=1), count=0, baseline_index=0)
    assert recent == []
    Repo(db).upsert(
        "tree_points",
        {"id": "tp", "capture_id": ids[2], "created_at": TS, "points": [], "tier": "t", "model": None,
         "ai_call_id": None},
        sync=False,
    )  # fmt: skip
    Repo(db).insert(
        "ledger_records", ledger_row_citing({"captures": [{"id": ids[3], "role": "latest"}]}), sync=False
    )
    assert Retention(db, media, clock).thin_captures() == 1
    assert remaining_capture_ids(db) == {ids[0], ids[2], ids[3]}
    assert Retention(db, media, clock).thin_captures() == 0


def test_ledger_protection_matches_capture_ids_exactly(db, media, clock):  # M1 follow-up (ruling R6b)
    ids = seed_captures(db, media, minute=clock.now() - timedelta(hours=25), count=3, baseline_index=0)
    # ids[1] appears only inside another string (a node ID, a note): it is not referenced evidence
    evidence = {"captures": [{"id": ids[2], "role": "latest"}], "note": f"x{ids[1]}x",
                "telemetry_window": {"node_ids": [ids[1] + "-node"]}}  # fmt: skip
    Repo(db).insert("ledger_records", ledger_row_citing(evidence), sync=False)
    assert Retention(db, media, clock).thin_captures() == 1
    assert remaining_capture_ids(db) == {ids[0], ids[2]}


def test_thinning_keeps_uploaded_media_rows_so_budget_still_counts_and_prunes(db, media, clock, fake_cloud):
    ids = seed_captures(db, media, minute=clock.now() - timedelta(hours=25), count=2, baseline_index=0)
    repo = Repo(db)
    for k in media_keys(ids[1]):
        repo.upsert(
            "media_objects",
            {
                "bucket": "captures", "key": k, "local_path": f"var/media/captures/{k}",
                "content_type": "image/jpeg", "bytes": 500, "protected": False, "state": "uploaded",
                "uploaded_at": TS, "attempts": 0, "last_error": None,
            },
            sync=False,
        )  # fmt: skip
    assert Retention(db, media, clock).thin_captures() == 1
    assert not media.path("captures", key_for(ids[1])).exists()
    rows = repo.query("select key from media_objects where state = 'uploaded'")
    assert sorted(r["key"] for r in rows) == sorted(media_keys(ids[1]))
    pruned = MediaBudget(db, fake_cloud, budget_bytes=100).enforce()
    assert sorted(k for _, k in pruned) == sorted(media_keys(ids[1]))


def test_thinning_skips_captures_with_pending_media_until_uploaded(db, media, clock):
    ids = seed_captures(db, media, minute=clock.now() - timedelta(hours=25), count=2, baseline_index=0)
    media.put("captures", key_for(ids[1]), b"x", "image/jpeg", cloud=True)  # pending
    assert Retention(db, media, clock).thin_captures() == 0
    assert remaining_capture_ids(db) == set(ids)
    assert media.path("captures", key_for(ids[1])).exists()
    with db.tx() as conn:
        conn.execute("UPDATE media_objects SET state = 'uploaded' WHERE state = 'pending'")
    assert Retention(db, media, clock).thin_captures() == 1


async def test_run_survives_unexpected_drain_exception_and_recovers(world, clock, db, offline_calls, caplog):
    """Finding 1: a local fault raised outside the cloud try/except must not kill the loop."""
    import sqlite3

    repo, worker, fake = world
    repo.upsert("sites", site("KSL"))
    real_ack = worker.outbox.ack
    faults = {"left": 3}

    def flaky_ack(seqs):
        if faults["left"]:
            faults["left"] -= 1
            raise sqlite3.OperationalError("database is locked SECRET-ROW-DATA")
        return real_ack(seqs)

    worker.outbox.ack = flaky_ack

    async def settle():
        await asyncio.sleep(0.05)

    task = asyncio.create_task(worker.run())
    try:
        await settle()
        assert not task.done()
        assert worker._failures == 1 and worker.status().state == "buffering"
        clock.advance(1)
        await settle()
        clock.advance(2)
        await settle()
        assert not task.done() and worker._failures == 3
        assert offline_calls == [True]  # same offline path as cloud failures
        clock.advance(4)
        await settle()
        assert not task.done()
        assert Outbox(db).count() == 0 and worker.status().state == "online"
        assert offline_calls == [True, False]
        assert len(fake.tables["sites"]) == 1  # retried upsert stays idempotent
    finally:
        task.cancel()
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "OperationalError" in logged and "SECRET-ROW-DATA" not in logged


class _PoisonCloud(FakeCloudTarget):
    """Rejects uploads of one key forever; everything else succeeds."""

    def __init__(self, poison_key):
        super().__init__()
        self.poison_key = poison_key

    def upload(self, bucket, key, data, content_type):
        if key == self.poison_key:
            raise ValueError("object rejected")
        super().upload(bucket, key, data, content_type)


async def test_poison_media_object_is_marked_failed_and_does_not_block_queue(db, media, clock):
    """M1 deferred R9: a permanently failing object must not block later uploads nor sync health."""
    from bcs_gs.store.sync import MEDIA_MAX_ATTEMPTS

    bad, good = key_for("c1"), key_for("c2")
    cloud = _PoisonCloud(bad)
    offline = []
    worker = SyncWorker(db, media, cloud, EventBus(clock), clock, on_offline=offline.append)
    media.put("captures", bad, b"bad", "image/jpeg", cloud=True)
    media.put("captures", good, b"good", "image/jpeg", cloud=True)
    results = []
    for i in range(MEDIA_MAX_ATTEMPTS):
        repo_row = site(f"S{i}")  # row traffic: the cloud is evidently reachable
        Repo(db).upsert("sites", repo_row)
        state = Repo(db).query("select state from media_objects where key = ?", (bad,))[0]["state"]
        assert state == "pending"  # not failed before MEDIA_MAX_ATTEMPTS evidence-backed failures
        results.append(await worker.drain_once())
    assert ("captures", good) in cloud.objects  # the later object proceeds
    assert all(r.ok for r in results) and offline == [] and worker._failures == 0  # no back-off growth
    rows = {r["key"]: r for r in Repo(db).query("select key, state, attempts, last_error from media_objects")}
    assert rows[bad]["state"] == "failed" and rows[bad]["attempts"] == MEDIA_MAX_ATTEMPTS
    assert rows[bad]["last_error"] and rows[good]["state"] == "uploaded"
    st = worker.status()
    assert st.media_queue == 0 and st.media_failed == 1  # skipped (kept on disk) and visible
    assert media.path("captures", bad).exists()
    assert (await worker.drain_once()).ok


async def test_idle_poison_media_alone_keeps_sync_healthy(db, media, clock):
    """Fix round 2: the poison object is the only pending work and no rows are queued."""
    from bcs_gs.store.sync import MEDIA_MAX_ATTEMPTS

    bad = key_for("c1")
    cloud = _PoisonCloud(bad)
    offline = []
    worker = SyncWorker(db, media, cloud, EventBus(clock), clock, on_offline=offline.append)
    media.put("captures", key_for("c0"), b"ok", "image/jpeg", cloud=True)
    assert (await worker.drain_once()).ok  # an earlier good upload
    media.put("captures", bad, b"bad", "image/jpeg", cloud=True)
    results = []
    for _ in range(MEDIA_MAX_ATTEMPTS):
        assert (
            Repo(db).query("select state from media_objects where key = ?", (bad,))[0]["state"] == "pending"
        )
        results.append(await worker.drain_once())
    assert all(r.ok for r in results) and offline == [] and worker._failures == 0
    row = Repo(db).query("select state, attempts from media_objects where key = ?", (bad,))[0]
    assert row["state"] == "failed" and row["attempts"] == MEDIA_MAX_ATTEMPTS
    assert worker.status().media_failed == 1 and worker.status().media_queue == 0


class _StorageDownCloud(FakeCloudTarget):
    """Database up, Storage down: row writes succeed, uploads and the Storage probe fail."""

    def upload(self, bucket, key, data, content_type):
        raise ValueError("storage unavailable")

    def probe(self, bucket):
        raise ValueError("storage unavailable")


async def test_storage_outage_with_rows_acking_never_fails_media(db, media, clock):
    from bcs_gs.store.sync import MEDIA_MAX_ATTEMPTS

    cloud = _StorageDownCloud()
    worker = SyncWorker(db, media, cloud, EventBus(clock), clock, on_offline=lambda _: None)
    media.put("captures", key_for("c1"), b"a", "image/jpeg", cloud=True)
    media.put("captures", key_for("c2"), b"b", "image/jpeg", cloud=True)
    for i in range(MEDIA_MAX_ATTEMPTS * 3):
        Repo(db).upsert("sites", site(f"S{i}"))  # normal row traffic keeps acking
        r = await worker.drain_once()
        assert r.rows == 1 and not r.ok  # rows went through; the Storage outage still fails the pass
    states = {x["state"] for x in Repo(db).query("select state from media_objects")}
    assert states == {"pending"} and worker.status().media_failed == 0


async def test_outage_with_only_media_pending_goes_offline_and_fails_nothing(db, media, clock):
    from bcs_gs.store.sync import MEDIA_MAX_ATTEMPTS

    cloud = FakeCloudTarget()
    offline = []
    worker = SyncWorker(db, media, cloud, EventBus(clock), clock, on_offline=offline.append)
    media.put("captures", key_for("c0"), b"ok", "image/jpeg", cloud=True)
    assert (await worker.drain_once()).ok
    cloud.failing = True  # outage: the probe fails too
    media.put("captures", key_for("c1"), b"a", "image/jpeg", cloud=True)
    for _ in range(MEDIA_MAX_ATTEMPTS * 3):
        assert not (await worker.drain_once()).ok
    assert offline == [True] and worker._failures == MEDIA_MAX_ATTEMPTS * 3
    assert (
        Repo(db).query("select state from media_objects where key = ?", (key_for("c1"),))[0]["state"]
        == "pending"
    )


async def test_outage_does_not_mark_media_failed(db, media, clock):
    from bcs_gs.store.sync import MEDIA_MAX_ATTEMPTS

    cloud = FakeCloudTarget(failing=True)
    offline = []
    worker = SyncWorker(db, media, cloud, EventBus(clock), clock, on_offline=offline.append)
    media.put("captures", key_for("c1"), b"a", "image/jpeg", cloud=True)
    for i in range(MEDIA_MAX_ATTEMPTS * 3):
        Repo(db).upsert("sites", site(f"S{i}"))  # rows fail too: nothing is acknowledged
        assert not (await worker.drain_once()).ok
    assert offline == [True]  # a true outage still goes offline
    assert Repo(db).query("select state from media_objects")[0]["state"] == "pending"
    cloud.failing = False
    assert (await worker.drain_once()).ok
    st = Repo(db).query("select state from media_objects")[0]["state"]
    assert st == "uploaded" and worker.status().media_failed == 0 and offline == [True, False]


async def test_capture_media_state_becomes_uploaded_once_all_its_media_is_up(world, media, db):
    repo, worker, fake = world
    cid = "0199cccc-0000-7000-8000-000000000001"
    keys = media_keys(cid)
    repo.upsert(
        "captures",
        {**capture_row(cid, media_state="local"), "media": {"image": keys[0], "height": keys[1]}},
        sync=False,
    )
    media.put("captures", keys[0], b"a", "image/jpeg", cloud=True)
    media.put("captures", keys[1], b"b", "image/png", cloud=False)  # not yet eligible
    await worker.drain_once()
    assert capture_row_db(db, cid)["media_state"] == "local"  # one object still local
    media.promote("captures", [keys[1]])
    await worker.drain_once()
    assert capture_row_db(db, cid)["media_state"] == "uploaded"
    await worker.drain_once()  # the synced capture row reaches the cloud
    synced = [r for r in fake.tables.get("captures", {}).values() if r["id"] == cid]
    assert synced and synced[-1]["media_state"] == "uploaded"


async def test_pruned_capture_media_state_is_never_overwritten(world, media, db):
    repo, worker, _fake = world
    cid = "0199cccc-0000-7000-8000-000000000002"
    key = key_for(cid)
    repo.upsert("captures", {**capture_row(cid, media_state="pruned"), "media": {"image": key}}, sync=False)
    media.put("captures", key, b"a", "image/jpeg", cloud=True)
    await worker.drain_once()
    assert capture_row_db(db, cid)["media_state"] == "pruned"


# ---- poison-row policy (dead letter) -----------------------------------------------------------
class PoisonCloud(FakeCloudTarget):
    """Rejects any row whose id is in ``poison`` the way a Postgres CHECK violation would."""

    def __init__(self, poison):
        super().__init__()
        self.poison = set(poison)

    def upsert(self, table, rows, on_conflict):
        if any(r["id"] in self.poison for r in rows):
            raise CloudError("APIError: new row violates check constraint", permanent=True)
        super().upsert(table, rows, on_conflict)


@pytest.fixture
def poison_world(db, media, clock):
    cloud = PoisonCloud({"poison"})
    offline = []
    worker = SyncWorker(db, media, cloud, EventBus(clock), clock, on_offline=offline.append)
    return Repo(db), worker, cloud, offline


def _dead(db):
    return Repo(db).query("select seq, table_name, last_error from sync_dead_letter order by seq")


async def test_permanently_rejected_head_row_is_dead_lettered_and_the_queue_moves_on(poison_world, db, caplog):
    repo, worker, cloud, offline = poison_world
    repo.upsert("alerts", {**alert_row(0), "id": "poison", "message": "PAYLOAD-MARKER"})
    repo.upsert("alerts", alert_row(1))
    repo.upsert("alerts", alert_row(2))
    with caplog.at_level("WARNING", logger="bcs_gs.sync"):
        result = await worker.drain_once()
    assert result.ok and result.rows == 2 and offline == []  # a rejected row is not a cloud outage
    st = worker.status()
    assert st.queue == 0 and st.dead_letter == 1 and st.state == "online"
    assert [(d["table_name"]) for d in _dead(db)] == ["alerts"]
    assert {r["id"] for r in cloud.tables_in_order("alerts")} == {alert_row(1)["id"], alert_row(2)["id"]}
    warn = [r.getMessage() for r in caplog.records if "dead letter" in r.getMessage()]
    assert len(warn) == 1 and "alerts" in warn[0] and "row 1" in warn[0]
    assert "PAYLOAD-MARKER" not in caplog.text  # ids and table only, never the payload


async def test_poison_row_inside_a_batch_is_isolated_and_the_rest_still_sync(poison_world, db):
    repo, worker, cloud, _ = poison_world
    repo.upsert("alerts", alert_row(0))
    repo.upsert("alerts", {**alert_row(1), "id": "poison"})
    repo.upsert("alerts", alert_row(2))
    assert (await worker.drain_once()).ok
    assert worker.status().queue == 0 and worker.status().dead_letter == 1
    assert {r["id"] for r in cloud.tables_in_order("alerts")} == {alert_row(0)["id"], alert_row(2)["id"]}


async def test_dead_letter_needs_five_consecutive_permanent_failures(poison_world, db):
    from bcs_gs.store.sync import OUTBOX_MAX_PERMANENT_FAILURES

    assert OUTBOX_MAX_PERMANENT_FAILURES == 5
    repo, worker, cloud, _ = poison_world
    repo.upsert("alerts", {**alert_row(0), "id": "poison"})
    calls = []
    real = cloud.upsert
    cloud.upsert = lambda t, rows, pk: (calls.append(1), real(t, rows, pk))[1]
    await worker.drain_once()
    assert len(calls) == 5 and worker.status().dead_letter == 1


async def test_transient_failures_never_dead_letter(world, db, offline_calls):
    repo, worker, fake = world
    repo.upsert("alerts", alert_row(0))
    fake.failing = True  # CloudError(permanent=False): network, 5xx, 429
    for _ in range(12):
        assert not (await worker.drain_once()).ok
    st = worker.status()
    assert st.queue == 1 and st.dead_letter == 0 and offline_calls == [True]
    fake.failing = False
    assert (await worker.drain_once()).ok and worker.status().queue == 0


@pytest.mark.parametrize(
    ("code", "permanent"),
    [("23514", True), ("23505", True), ("22P02", True), ("400", True), ("409", True),
     ("422", True), ("42501", False), ("42P01", False), ("42703", False), ("404", False), ("PGRST205", False), ("401", False), ("403", False), ("429", False), ("503", False),
     ("08006", False), ("57014", False), ("PGRST301", False), (None, False)],
)  # fmt: skip
def test_permanent_rejection_classification(code, permanent):
    from bcs_gs.store.cloud import is_permanent_rejection

    class E(Exception):
        pass

    e = E("x")
    e.code = code
    assert is_permanent_rejection(e) is permanent
    assert is_permanent_rejection(ConnectionError("down")) is False


def test_conditional_update_never_overwrites_a_concurrent_write(db):
    repo = Repo(db)
    cid = "0199cccc-0000-7000-8000-0000000000aa"
    repo.upsert("captures", capture_row(cid, media_state="local"), sync=False)
    # A baseline write lands between a reader's read and its update:
    repo.upsert("captures", {**capture_row(cid, media_state="local"), "is_baseline": True,
                             "retention_reason": "baseline"}, sync=False)  # fmt: skip
    assert repo.update_if("captures", {"id": cid}, {"media_state": "uploaded"}, {"media_state": "local"})
    row = capture_row_db(db, cid)
    assert row["media_state"] == "uploaded" and row["is_baseline"] and row["retention_reason"] == "baseline"
    queued = repo.query("select payload from sync_outbox where table_name = 'captures'")
    assert len(queued) == 1 and json.loads(queued[0]["payload"])["is_baseline"] is True
    # The expectation no longer holds: nothing changes, nothing is queued.
    assert not repo.update_if("captures", {"id": cid}, {"media_state": "pruned"}, {"media_state": "local"})
    assert capture_row_db(db, cid)["media_state"] == "uploaded"
    assert len(repo.query("select 1 from sync_outbox where table_name = 'captures'")) == 1


class SchemaDriftCloud(FakeCloudTarget):
    def __init__(self, code):
        super().__init__()
        self.code = code

    def upsert(self, table, rows, on_conflict):
        from bcs_gs.store.cloud import is_permanent_rejection

        e = Exception("relation does not exist")
        e.code = self.code
        raise CloudError("APIError", permanent=is_permanent_rejection(e))


@pytest.mark.parametrize("code", ["42P01", "42703", "PGRST205"])
async def test_schema_level_rejection_waits_and_never_dead_letters(db, media, clock, code):
    worker = SyncWorker(db, media, SchemaDriftCloud(code), EventBus(clock), clock, on_offline=lambda _: None)
    repo = Repo(db)
    for i in range(3):
        repo.upsert("alerts", alert_row(i))
    for _ in range(3):
        assert not (await worker.drain_once()).ok
    st = worker.status()
    assert st.queue == 3 and st.dead_letter == 0


def test_thinning_futures_deletes_local_media_of_unretained_forecasts_only(db, media, clock):
    repo = Repo(db)
    for i in range(5):  # f0..f4 all ready; the latest three (f2..f4) are retained
        repo.upsert(
            "forecasts",
            {
                "id": f"f{i}", "created_at": to_iso(T0 + timedelta(minutes=i)), "status": "ready",
                "plan_version_id": None, "base_capture_id": "c", "input_hash": "h", "parameters": {},
                "parameter_sources": {}, "keyframes": {}, "summary": {}, "bands": {},
            },
            sync=False,
        )  # fmt: skip
        media.put("futures", f"f{i}/base/1/texture.jpg", b"x", "image/jpeg", cloud=False)
        media.put("futures", f"f{i}/base/1/height.png", b"x", "image/png", cloud=False)
    media.put("futures", "gone/base/1/texture.jpg", b"x", "image/jpeg", cloud=False)  # forecast row deleted
    media.put("futures", "f1/with/1/texture.jpg", b"x", "image/jpeg", cloud=False, protected=True)
    repo.upsert(
        "media_objects",
        {
            "bucket": "futures", "key": "f0/base/1/texture.jpg", "local_path": "p", "content_type": "image/jpeg",
            "bytes": 1, "protected": False, "state": "uploaded", "uploaded_at": to_iso(T0), "attempts": 0,
            "last_error": None,
        },
        sync=False,
    )  # fmt: skip
    assert Retention(db, media, clock).thin_futures() == 2  # f0 and gone; f1 holds a protected file
    p = media.path
    assert not p("futures", "f0/base/1/texture.jpg").exists() and not p("futures", "gone/base/1/texture.jpg").exists()
    assert p("futures", "f1/base/1/texture.jpg").exists() and p("futures", "f1/with/1/texture.jpg").exists()
    assert all(p("futures", f"f{i}/base/1/height.png").exists() for i in (1, 2, 3, 4))
    # the uploaded object's row stays: its cloud copy still exists and counts against the budget
    rows = repo.query("SELECT key, state FROM media_objects WHERE key LIKE 'f0/%'")
    assert [(r["key"], r["state"]) for r in rows] == [("f0/base/1/texture.jpg", "uploaded")]
