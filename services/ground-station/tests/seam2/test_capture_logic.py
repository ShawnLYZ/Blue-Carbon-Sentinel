"""CaptureService (Task 8): triggers, quality, sharpest frame, artefacts, baseline, cloud eligibility.

Generated arrays and seeded numbers only. The service is driven with stand-in imagery, camera,
calibration and reality objects that hand out generated SiteRasters.
"""

import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcs_gs.api.events import EVENT_DATA
from bcs_gs.camera.imagery import SiteRaster
from bcs_gs.capture import (
    BaselineConflict,
    CameraOffline,
    CaptureService,
    ChangeTrigger,
    cloud_eligible,
    frame_difference,
    is_evidence_grade,
    pick_sharpest,
    quality_metrics,
    should_become_baseline,
    write_artefacts,
)
from bcs_gs.core.clock import ManualClock
from bcs_gs.core.events import EventBus
from bcs_gs.store.db import Database
from bcs_gs.store.media import MediaStore
from bcs_gs.store.repo import Repo
from bcs_gs.vegetation import classify_raster, vari
from vegetation_helpers import CFG, GREEN, REGISTRY, zone_box

T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)


# ---- generated rasters ------------------------------------------------------------------------
def checker(lo=60, hi=190, cell=8):
    yy, xx = np.indices((512, 512))
    g = np.where(((yy // cell) + (xx // cell)) % 2 == 0, lo, hi).astype(np.uint8)
    return np.dstack([g, g, g])


def sharp_generated_raster():
    return checker()


def blurred_generated_raster(sigma):
    img = checker()
    if sigma:
        img = cv2.GaussianBlur(img, (0, 0), sigma)
    return SiteRaster(img, ("R", "G", "B"), T0, "esp32cam", int(sigma * 10), "cal-1")


def canopy_scene(seed=0, canopy=True):
    """Background with a textured green canopy in zone B3 (sharp, mean 40-220, nothing clipped)."""
    rng = np.random.default_rng(seed)
    img = np.full((512, 512, 3), (120, 110, 100), np.uint8)
    if canopy:
        v0, v1, u0, u1 = zone_box()
        img[v0:v1, u0:u1] = GREEN
    noise = rng.integers(-25, 26, size=img.shape)
    return np.clip(img.astype(np.int16) + noise, 1, 254).astype(np.uint8)


def decode_indexed_png(data):
    """(width, height, bit depth, colour type), PLTE bytes and the index array of a filter-0 PNG."""
    import struct
    import zlib

    assert data[:8] == bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])
    pos, chunks = 8, {}
    while pos < len(data):
        (n,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunks[kind] = chunks.get(kind, b"") + data[pos + 8 : pos + 8 + n]
        pos += 12 + n
    w, h, depth, ctype = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    raw = np.frombuffer(zlib.decompress(chunks[b"IDAT"]), np.uint8).reshape(h, w + 1)
    assert not raw[:, 0].any()  # filter type 0 on every row
    return (w, h, depth, ctype), chunks[b"PLTE"], raw[:, 1:]


# ---- pure logic (brief Step 1) -------------------------------------------------------------------
def test_change_capture_only_after_2s_stable_and_above_threshold():
    t = ChangeTrigger()
    now = T0
    assert not t.observe(diff_prev=9.0, diff_last_capture=9.0, now=now)  # moving
    assert not t.observe(diff_prev=1.0, diff_last_capture=9.0, now=now + timedelta(seconds=1.9))
    assert t.observe(diff_prev=1.0, diff_last_capture=9.0, now=now + timedelta(seconds=2.0))
    assert not t.observe(diff_prev=1.0, diff_last_capture=3.0, now=now + timedelta(seconds=5))  # unchanged


def test_no_change_capture_while_motion_continues():  # Review Focus 2
    t = ChangeTrigger()
    for i in range(30):
        assert not t.observe(diff_prev=8.0, diff_last_capture=20.0, now=T0 + timedelta(seconds=i))
    assert t.moving


def test_unlocked_capture_is_not_evidence_grade_and_not_baseline():  # Review Focus 3
    q = quality_metrics(sharp_generated_raster(), moving=False, exposure_locked=False)
    assert q.exposure_locked is False and not is_evidence_grade(q)
    assert is_evidence_grade(quality_metrics(sharp_generated_raster(), moving=False, exposure_locked=True))
    assert not should_become_baseline(evidence_grade=False, has_baseline=False)
    assert should_become_baseline(evidence_grade=True, has_baseline=False)
    assert not should_become_baseline(evidence_grade=True, has_baseline=True)


def test_quality_limits_n11():
    flat = np.full((512, 512, 3), 128, np.uint8)
    assert not is_evidence_grade(quality_metrics(flat, moving=False, exposure_locked=True))  # blurry
    assert not is_evidence_grade(quality_metrics(checker(), moving=True, exposure_locked=True))  # motion
    dark = checker(lo=5, hi=40)
    assert quality_metrics(dark, moving=False, exposure_locked=True).mean < 40
    clipped = checker(lo=0, hi=255)
    q = quality_metrics(clipped, moving=False, exposure_locked=True)
    assert q.clipped_pct == pytest.approx(100.0) and not is_evidence_grade(q)


def test_pick_sharpest_of_last_five():
    rs = [blurred_generated_raster(sigma) for sigma in (5, 3, 0, 4, 2)]
    assert pick_sharpest(rs) is rs[2]


def test_cloud_eligibility_rules_a2():
    assert cloud_eligible("change", False, False, False, 1.0, True)
    assert cloud_eligible("interval", True, False, False, 1.0, True)  # flagged
    assert cloud_eligible("interval", False, False, False, 2.0, minute_already_sent=False)  # first unchanged
    assert not cloud_eligible("interval", False, False, False, 2.0, minute_already_sent=True)
    assert cloud_eligible("manual", False, False, False, 0.0, True)
    assert cloud_eligible("interval", False, True, False, 0.0, True)  # baseline
    assert cloud_eligible("interval", False, False, True, 0.0, True)  # referenced
    assert not cloud_eligible(
        "interval", False, False, False, 9.0, True
    )  # A2 literal: score alone never sends
    assert not cloud_eligible("interval", False, False, False, None, True)  # None counts as unchanged
    assert cloud_eligible("interval", False, False, False, None, False)
    assert not cloud_eligible("interval", False, False, False, 9.0, minute_already_sent=False)  # changed


def test_frame_difference_scale():
    a = np.zeros((512, 512, 3), np.uint8)
    b = np.full((512, 512, 3), 10, np.uint8)
    assert frame_difference(a, b) == pytest.approx(10, abs=0.5)
    assert frame_difference(a, a) == 0


def test_artefacts_under_h5_keys(tmp_path):
    db = Database(tmp_path / "bcs.sqlite3", ManualClock(T0))
    db.migrate()
    media = MediaStore(tmp_path, db)
    img = canopy_scene()
    classes = classify_raster(img, None, CFG)
    height = np.arange(256 * 256, dtype=np.uint32).reshape(256, 256).astype(np.uint16)
    keys = write_artefacts(media, "cap-1", T0, img, height, classes, vari(img), cloud=False)
    assert keys == {
        k: f"2026/10/16/cap-1/{n}"
        for k, n in (("image", "image.jpg"), ("height", "height.png"), ("classes", "classes.png"),
                     ("ndvi", "ndvi.png"))
    }  # fmt: skip
    h = cv2.imread(str(media.path("captures", keys["height"])), cv2.IMREAD_UNCHANGED)
    assert h.dtype == np.uint16 and np.array_equal(h, height)
    nd = cv2.imread(str(media.path("captures", keys["ndvi"])), cv2.IMREAD_UNCHANGED)
    expect = np.rint((vari(img).astype(np.float64) + 1) / 2 * 65535).astype(np.uint16)
    assert nd.dtype == np.uint16 and np.array_equal(nd, expect)
    data = media.path("captures", keys["classes"]).read_bytes()  # H5: 8-bit indexed (palette) PNG
    ihdr, plte, codes = decode_indexed_png(data)
    assert ihdr == (512, 512, 8, 3) and len(plte) == 5 * 3
    assert np.array_equal(codes, classes)
    assert cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape == (512, 512, 3)
    states = {r["state"] for r in Repo(db).query("select state from media_objects")}
    assert states == {"local_only"}
    db.close()


# ---- service harness --------------------------------------------------------------------------
class StubImagery:
    source_id = "esp32cam"

    def __init__(self, clock):
        self.clock = clock
        self.rasters: list[SiteRaster] = []
        self.is_online = True
        self.cal_id = "cal-1"
        self._q: asyncio.Queue = asyncio.Queue()
        self._seq = 0

    def push(self, img, *, at=None, stream=False):
        self._seq += 1
        r = SiteRaster(img, ("R", "G", "B"), at or self.clock.now(), "esp32cam", self._seq, self.cal_id)
        if stream:  # a live stream fills the recent window; a still shot replaces it
            self.rasters = [*self.rasters, r][-5:]
            self._q.put_nowait(r)
        else:
            self.rasters = [r]
        return r

    def online(self):
        return self.is_online

    def latest(self):
        return self.rasters[-1] if self.rasters else None

    def recent(self, n):
        return self.rasters[-n:]

    async def subscribe(self):
        while True:
            yield await self._q.get()


class StubCamera:
    def __init__(self, imagery):
        self.imagery = imagery
        self.locked = True

    def status(self):
        return SimpleNamespace(online=self.imagery.is_online, locked=self.locked)


class StubCalibration:
    def __init__(self):
        self.id = "cal-1"

    def active(self):
        return SimpleNamespace(id=self.id)


class StubReality:
    def latest(self):
        return None


class World:
    def __init__(self, tmp_path, *, test_mode=True):
        self.clock = ManualClock(T0)
        self.db = Database(tmp_path / "bcs.sqlite3", self.clock)
        self.db.migrate()
        self.repo = Repo(self.db)
        for z in REGISTRY.zones():  # zone_metrics has a foreign key to zones
            self.repo.upsert("sites", {
                "id": "KSL", "name": "KSL", "status": "live", "region": "r", "centre_lat": 0.0,
                "centre_lng": 0.0, "anchor_nw_lat": None, "anchor_nw_lng": None, "bearing_deg": 0.0,
                "size_m": 500.0, "scale_label": None, "rationale": "x", "updated_at": "2026-10-16T00:00:00.000Z",
            }, sync=False)  # fmt: skip
            self.repo.upsert("zones", {
                "id": z.id, "site_id": "KSL", "label": z.label, "coordinate_id": z.coordinate_id,
                "col": z.col, "row": z.row, "bounds": [], "bounds_site_m": [], "centre_lat": 0.0,
                "centre_lng": 0.0, "area_ha": 1.0,
            }, sync=False)  # fmt: skip
        self.media = MediaStore(tmp_path, self.db)
        self.bus = EventBus(self.clock)
        self.events = self.bus.subscribe()
        self.imagery = StubImagery(self.clock)
        self.camera = StubCamera(self.imagery)
        self.calibration = StubCalibration()
        self.svc = CaptureService(
            repo=self.repo, media=self.media, bus=self.bus, clock=self.clock, imagery=self.imagery,
            camera=self.camera, calibration=self.calibration, reality=StubReality(), site=REGISTRY,
            thresholds=CFG, test_mode=test_mode,
        )  # fmt: skip

    def drain(self, type_=None):
        out = []
        while self.events._queue:
            e = self.events._queue.popleft()
            if type_ is None or e.type == type_:
                out.append(e)
        return out

    def outbox_ids(self, table):
        rows = self.repo.query("select payload from sync_outbox where table_name = ?", (table,))
        import json

        return [
            json.loads(r["payload"]).get("id") or json.loads(r["payload"]).get("capture_id") for r in rows
        ]

    def media_states(self, capture_id):
        return {
            r["state"]
            for r in self.repo.query(
                "select state from media_objects where key like ?", (f"%/{capture_id}/%",)
            )
        }


@pytest.fixture
async def world(tmp_path):
    w = World(tmp_path)
    yield w
    await w.svc.stop()
    w.db.close()


async def wait_until(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def validate(event):
    EVENT_DATA[event.type].model_validate(event.data)


# ---- service: real captures ---------------------------------------------------------------------
async def test_manual_capture_writes_rows_media_events_and_auto_baseline(world):
    world.imagery.push(canopy_scene())
    t = time.perf_counter()
    cap = await world.svc.capture_now("manual")
    elapsed = time.perf_counter() - t
    print(f"manual capture took {elapsed * 1000:.0f} ms")
    assert elapsed <= 1.5
    assert cap.trigger == "manual" and cap.evidence_grade and cap.is_baseline  # first evidence-grade
    assert cap.calibration_id == "cal-1" and len(cap.zone_metrics) == 25
    row = world.repo.get("captures", {"id": cap.id})
    assert row["retention_reason"] == "baseline" and row["media_state"] == "local"
    assert set(row["media"]) == {"image", "height", "classes", "ndvi"}
    for key in row["media"].values():
        assert world.media.path("captures", key).exists()
    assert world.media_states(cap.id) == {"pending"}  # manual + baseline: cloud-eligible
    assert cap.id in world.outbox_ids("captures")
    b3 = next(z for z in cap.zone_metrics if z.zone_id == "KSL-B3")
    assert b3.canopy_pct > 50
    events = world.drain()
    types = [e.type for e in events]
    assert types.count("capture.created") == 1 and types.count("zone.metrics") == 1
    assert types.count("baseline.updated") == 1
    for e in events:
        validate(e)
    assert world.svc.baseline().id == cap.id


async def test_capture_against_baseline_flags_canopy_loss(world):
    world.imagery.push(canopy_scene(0))
    base = await world.svc.capture_now("manual")
    world.drain()
    world.clock.advance(20)
    world.imagery.push(canopy_scene(1, canopy=False))
    cap = await world.svc.capture_now("manual")
    assert not cap.is_baseline and cap.flagged
    b3 = next(z for z in cap.zone_metrics if z.zone_id == "KSL-B3")
    assert b3.canopy_loss_pp is not None and b3.canopy_loss_pp > 50
    assert "canopy_loss" in [f.kind for f in b3.flags]
    flagged = world.drain("zone.flagged")
    assert [e.data["zone_id"] for e in flagged] == ["KSL-B3"]
    validate(flagged[0])
    assert cap.change_score is not None and cap.change_score > 0
    assert world.svc.baseline().id == base.id


async def test_manual_capture_while_offline_raises(world):
    world.imagery.push(canopy_scene())
    world.imagery.is_online = False
    with pytest.raises(CameraOffline):
        await world.svc.capture_now("manual")
    assert world.repo.query("select id from captures") == []


async def test_interval_trigger_pauses_while_camera_offline(world):
    world.imagery.push(canopy_scene())
    world.imagery.is_online = False
    world.svc.start()
    await asyncio.sleep(0.05)
    world.clock.advance(10)
    await asyncio.sleep(0.2)
    assert world.repo.query("select id from captures") == []
    world.imagery.is_online = True
    world.clock.advance(10)
    await wait_until(lambda: len(world.repo.query("select id from captures")) == 1)
    assert world.repo.query("select trigger from captures")[0]["trigger"] == "interval"


async def test_interval_capture_while_moving_is_motion_tagged(world):
    world.imagery.push(canopy_scene())
    world.svc.trigger.observe(diff_prev=9.0, diff_last_capture=9.0, now=T0)
    cap = await world.svc.capture_now("interval")
    assert cap.quality.motion is True and not cap.evidence_grade and not cap.is_baseline


async def test_capture_just_after_motion_stops_is_still_motion_tagged(world):  # Review Focus 2/3
    t = world.svc.trigger
    t.observe(diff_prev=9.0, diff_last_capture=9.0, now=T0)  # moving
    t.observe(diff_prev=1.0, diff_last_capture=9.0, now=T0 + timedelta(seconds=0.5))  # quiet again
    assert not t.moving
    world.imagery.push(canopy_scene(), at=T0 + timedelta(seconds=0.5))
    cap = await world.svc.capture_now("interval")
    assert cap.quality.motion is True and not cap.evidence_grade and not cap.is_baseline
    t.observe(diff_prev=1.0, diff_last_capture=0.0, now=T0 + timedelta(seconds=2.5))
    world.imagery.push(canopy_scene(), at=T0 + timedelta(seconds=2.5))
    settled = await world.svc.capture_now("interval")
    assert settled.quality.motion is False and settled.evidence_grade and settled.is_baseline


async def test_unlocked_exposure_capture_is_never_baseline(world):
    world.camera.locked = False
    world.imagery.push(canopy_scene())
    cap = await world.svc.capture_now("manual")
    assert cap.quality.exposure_locked is False and not cap.evidence_grade and not cap.is_baseline
    assert world.svc.baseline() is None
    with pytest.raises(BaselineConflict):
        await world.svc.set_baseline(cap.id)


async def test_change_trigger_captures_once_after_stable_change(world):
    world.imagery.push(canopy_scene(0))
    await world.svc.capture_now("manual")
    world.svc.start()
    changed = canopy_scene(0)
    changed[:256] //= 3  # the top half goes dark: a large grey-level change
    for i in range(12):  # a new stable scene, one frame every 0.5 s of camera time
        world.imagery.push(changed, at=T0 + timedelta(seconds=30 + i * 0.5), stream=True)
        await asyncio.sleep(0.02)
    await wait_until(lambda: len(world.repo.query("select id from captures")) == 2)
    await asyncio.sleep(0.2)
    rows = world.repo.query("select trigger, change_score from captures order by taken_at")
    assert [r["trigger"] for r in rows] == ["manual", "change"]
    assert rows[1]["change_score"] > 6.0


async def test_cloud_eligibility_persisted_as_sync_flag(world):
    world.camera.locked = False  # keep baseline out of it
    world.imagery.push(canopy_scene(0))
    first = await world.svc.capture_now("interval")  # no previous capture: not "unchanged"
    world.clock.advance(10)
    world.imagery.push(canopy_scene(0))
    second = await world.svc.capture_now("interval")  # unchanged, minute already sent
    world.clock.advance(60)
    world.imagery.push(canopy_scene(0))
    third = await world.svc.capture_now("interval")  # first unchanged of a new minute
    assert second.change_score == pytest.approx(0.0)
    synced = world.outbox_ids("captures")
    assert first.id in synced and second.id not in synced and third.id in synced
    assert world.media_states(first.id) == {"pending"}
    assert world.media_states(second.id) == {"local_only"}
    metrics_synced = world.repo.query(
        "select count(*) as n from sync_outbox where table_name = 'zone_metrics' and payload like ?",
        (f'%"{second.id}"%',),
    )
    assert metrics_synced[0]["n"] == 0


async def test_manual_capture_does_not_use_up_the_minutes_interval_upload(world):
    world.camera.locked = False
    world.imagery.push(canopy_scene(0))
    manual = await world.svc.capture_now("manual")
    world.clock.advance(10)
    world.imagery.push(canopy_scene(0))
    interval = await world.svc.capture_now("interval")  # same UTC minute, first *interval* capture
    world.clock.advance(10)
    world.imagery.push(canopy_scene(0))
    second = await world.svc.capture_now("interval")
    synced = world.outbox_ids("captures")
    assert manual.id in synced and interval.id in synced and second.id not in synced


async def test_changed_interval_capture_does_not_use_up_the_minute(world):
    world.camera.locked = False
    world.imagery.push(canopy_scene(0))
    first = await world.svc.capture_now("interval")  # None score counts as unchanged: sent
    world.clock.advance(60)
    changed = canopy_scene(0)
    changed[:256] //= 3
    world.imagery.push(changed)
    moved = await world.svc.capture_now("interval")  # changed (> 6), unflagged: not sent (A2)
    world.clock.advance(10)
    world.imagery.push(changed)
    unchanged = await world.svc.capture_now("interval")  # first unchanged of that minute: sent
    assert moved.change_score > 6 and not moved.flagged and unchanged.change_score == pytest.approx(0.0)
    synced = world.outbox_ids("captures")
    assert first.id in synced and moved.id not in synced and unchanged.id in synced
    assert world.media_states(moved.id) == {"local_only"}


# ---- seeded captures (addendum I4) --------------------------------------------------------------
async def test_seed_capture_produces_zone_flagged(world):
    base = await world.svc.seed_capture({"KSL-B3": {"canopy_pct": 60.0}}, evidence_grade=True)
    assert base.is_baseline and set(world.repo.get("captures", {"id": base.id})["media"]) == {
        "image", "height", "classes", "ndvi",
    }  # synthetic files (ruling R22a)
    world.drain()
    cap = await world.svc.seed_capture({"KSL-B3": {"canopy_pct": 45.0}}, evidence_grade=True)
    assert cap.trigger == "manual" and cap.flagged and not cap.is_baseline
    b3 = next(z for z in cap.zone_metrics if z.zone_id == "KSL-B3")
    assert b3.canopy_loss_pp == pytest.approx(15.0)
    flagged = world.drain("zone.flagged")
    assert [e.data["zone_id"] for e in flagged] == ["KSL-B3"]
    assert [f["kind"] for f in flagged[0].data["flags"]] == ["canopy_loss"]
    validate(flagged[0])
    stored = world.repo.query(
        "select flags from zone_metrics where capture_id = ? and zone_id = 'KSL-B3'", (cap.id,),
        table="zone_metrics",
    )  # fmt: skip
    assert stored[0]["flags"][0]["kind"] == "canopy_loss"


async def test_seed_capture_explicit_metrics_flag_without_baseline(world):
    cap = await world.svc.seed_capture(
        {"KSL-B3": {"dieback_pct": 20.0}}, evidence_grade=False, quality={"sharpness": 10.0}
    )
    assert cap.flagged and not cap.is_baseline and cap.quality.sharpness == 10.0
    assert [e.data["zone_id"] for e in world.drain("zone.flagged")] == ["KSL-B3"]


async def test_seed_capture_refused_outside_test_mode(tmp_path):
    w = World(tmp_path, test_mode=False)
    try:
        with pytest.raises(PermissionError):
            await w.svc.seed_capture({}, evidence_grade=True)
    finally:
        w.db.close()


async def test_auto_baseline_again_after_calibration_change(world):
    a = await world.svc.seed_capture({}, evidence_grade=True)
    b = await world.svc.seed_capture({}, evidence_grade=True)
    assert a.is_baseline and not b.is_baseline
    world.calibration.id = "cal-2"
    c = await world.svc.seed_capture({}, evidence_grade=False)
    assert not c.is_baseline  # not evidence-grade
    d = await world.svc.seed_capture({}, evidence_grade=True)
    assert d.is_baseline and world.svc.baseline().id == d.id
    old = world.repo.get("captures", {"id": a.id})
    assert old["is_baseline"] is False and old["retention_reason"] is None


async def test_set_baseline_rules(world):
    a = await world.svc.seed_capture({}, evidence_grade=True)  # auto baseline
    world.clock.advance(5)
    world.camera.locked = False
    b = await world.svc.seed_capture({}, evidence_grade=False)
    with pytest.raises(BaselineConflict):
        await world.svc.set_baseline(b.id)
    world.clock.advance(5)
    c = await world.svc.seed_capture({}, evidence_grade=True)
    assert not c.is_baseline
    world.drain()
    got = await world.svc.set_baseline(None)  # latest evidence-grade capture
    assert got.id == c.id and got.is_baseline
    rows = {r["id"]: r for r in world.repo.query("select * from captures", table="captures")}
    assert [i for i, r in rows.items() if r["is_baseline"]] == [c.id]
    assert rows[c.id]["retention_reason"] == "baseline" and rows[a.id]["retention_reason"] is None
    assert [e.data for e in world.drain("baseline.updated")] == [{"capture_id": c.id}]
    assert world.outbox_ids("captures").count(c.id) >= 2  # re-enqueued as a baseline


async def test_set_baseline_promotes_unsent_capture_media(world):
    world.imagery.push(canopy_scene(0))
    first = await world.svc.capture_now("manual")  # auto baseline
    world.clock.advance(10)
    world.imagery.push(canopy_scene(0))
    sent = await world.svc.capture_now("interval")  # first interval capture of the minute: sent
    assert sent.id in world.outbox_ids("captures")
    world.clock.advance(10)
    world.imagery.push(canopy_scene(0))
    later = await world.svc.capture_now("interval")  # evidence-grade, same minute: stays local
    assert later.evidence_grade and not later.is_baseline
    assert world.media_states(later.id) == {"local_only"} and later.id not in world.outbox_ids("captures")
    got = await world.svc.set_baseline(later.id)
    assert got.is_baseline and world.svc.baseline().id == later.id
    assert world.media_states(later.id) == {"pending"} and later.id in world.outbox_ids("captures")
    assert world.repo.get("captures", {"id": first.id})["is_baseline"] is False
    protected = world.repo.query(
        "select key, protected from media_objects where key like ?", (f"%/{later.id}/%",)
    )
    assert all(r["protected"] for r in protected)


# ---- baseline threshold restatement (final review finding 3) -----------------------------------
def pale_green_scene(seed=0):
    """Pale green background (ExG between 0.05 and the scene's Otsu threshold) and a strong canopy
    in B3: the pre-baseline default calls the background canopy, the baseline threshold does not."""
    rng = np.random.default_rng(seed)
    img = np.full((512, 512, 3), (110, 135, 90), np.uint8)
    v0, v1, u0, u1 = zone_box()
    img[v0:v1, u0:u1] = GREEN
    noise = rng.integers(-25, 26, size=img.shape)
    return np.clip(img.astype(np.int16) + noise, 1, 254).astype(np.uint8)


def _stored_canopy(world, capture_id):
    rows = world.repo.query(
        "select zone_id, canopy_pct from zone_metrics where capture_id = ?", (capture_id,)
    )
    return {r["zone_id"]: r["canopy_pct"] for r in rows}


def _classes_of(world, capture_id):
    key = world.repo.get("captures", {"id": capture_id})["media"]["classes"]
    return decode_indexed_png(world.media.path("captures", key).read_bytes())[2]


async def test_auto_baseline_is_classified_with_its_own_threshold(world):
    from bcs_gs.vegetation import baseline_ref_from

    img = pale_green_scene(0)
    t = baseline_ref_from(img, CFG, registry=REGISTRY).exg_threshold
    assert t > CFG.classification.canopy.exg_default
    pre = classify_raster(img, None, CFG)
    assert (pre == 1).mean() > 0.5  # the default threshold would call the pale background canopy
    world.imagery.push(img)
    base = await world.svc.capture_now("manual")
    assert base.is_baseline
    stored = _stored_canopy(world, base.id)
    assert stored["KSL-A1"] < 1 and stored["KSL-B3"] > 90
    assert {z.zone_id: z.canopy_pct for z in base.zone_metrics} == pytest.approx(stored)
    assert np.array_equal(_classes_of(world, base.id), classify_raster(img, t, CFG))
    # A later capture of the same scene shows no systematic canopy step against the baseline.
    world.clock.advance(20)
    world.imagery.push(img)
    later = await world.svc.capture_now("manual")
    for z in later.zone_metrics:
        assert z.canopy_pct == pytest.approx(stored[z.zone_id], abs=1e-9)
        assert z.canopy_loss_pp == pytest.approx(0.0, abs=1e-9)


async def test_set_baseline_restates_stored_metrics_and_classes(world):
    from bcs_gs.vegetation import baseline_ref_from

    world.imagery.push(canopy_scene(0))
    await world.svc.capture_now("manual")  # auto baseline with its own threshold
    world.clock.advance(20)
    img = pale_green_scene(1)
    world.imagery.push(img)
    cap = await world.svc.capture_now("manual")
    assert cap.evidence_grade and not cap.is_baseline
    before = _stored_canopy(world, cap.id)
    t = baseline_ref_from(img, CFG, registry=REGISTRY).exg_threshold
    want = classify_raster(img, t, CFG)
    assert not np.array_equal(_classes_of(world, cap.id), want)
    queued = world.outbox_ids("zone_metrics").count(cap.id)
    await world.svc.set_baseline(cap.id)
    after = _stored_canopy(world, cap.id)
    assert after != before and after["KSL-A1"] < 1
    assert world.outbox_ids("zone_metrics").count(cap.id) == queued + 25  # restated rows are synced
    assert np.array_equal(_classes_of(world, cap.id), want)
    assert world.media_states(cap.id) == {"pending"}
    assert world.svc.baseline().zone_metrics[0].canopy_pct == pytest.approx(after["KSL-A1"])


async def test_failed_set_baseline_leaves_the_class_map_and_database_in_agreement(world, monkeypatch):
    world.imagery.push(canopy_scene(0))
    await world.svc.capture_now("manual")  # auto baseline
    world.clock.advance(20)
    world.imagery.push(pale_green_scene(1))
    cap = await world.svc.capture_now("manual")
    key = world.repo.get("captures", {"id": cap.id})["media"]["classes"]
    path = world.media.path("captures", key)
    before = path.read_bytes()
    states = world.media_states(cap.id)

    real = world.svc.repo.upsert

    def boom(table, row, **kw):
        if table == "zone_metrics":
            raise RuntimeError("disk full")
        return real(table, row, **kw)

    monkeypatch.setattr(world.svc.repo, "upsert", boom)
    with pytest.raises(RuntimeError):
        await world.svc.set_baseline(cap.id)
    monkeypatch.undo()
    assert path.read_bytes() == before  # the new class map was never put in place
    assert not list(path.parent.glob("*.tmp"))  # and no staged file is left behind
    assert not world.repo.get("captures", {"id": cap.id})["is_baseline"]
    assert world.media_states(cap.id) == states
