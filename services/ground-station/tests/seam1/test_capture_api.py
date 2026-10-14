"""Seam 1: camera, calibration, capture, baseline, media and zone routes (M2 rows of addendum I2).

The camera is offline in test mode; every capture here is seeded from numbers (I4). No image files."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from bcs_gs.api import routes_media

BASE = "/api/v1"
T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)  # the harness clock start


def metrics(**values: Any) -> dict[str, Any]:
    return values


async def seed(
    gs: Any, zone_metrics: dict[str, dict[str, Any]], *, evidence_grade: bool, **extra: Any
) -> dict:
    r = await gs.http.post(
        f"{BASE}/test/seed/capture",
        json={"zone_metrics": zone_metrics, "evidence_grade": evidence_grade, **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---- the brief's Seam 1 tests ----------------------------------------------------------------
async def test_manual_capture_without_camera_is_409(gs):
    r = await gs.http.post(f"{BASE}/captures")
    assert r.status_code == 409 and r.json()["error"]["code"] == "camera_offline"


async def test_seeded_capture_flags_zone_and_emits_events(gs):
    async with gs.events() as ev:
        base = await seed(gs, {"KSL-B3": metrics(canopy_pct=60)}, evidence_grade=True)
        await gs.http.post(f"{BASE}/baseline", json={"capture_id": base["id"]})
        await seed(gs, {"KSL-B3": metrics(canopy_pct=45, canopy_loss_pp=15)}, evidence_grade=True)
        flagged = await ev.wait_for("zone.flagged", lambda d: d["data"]["zone_id"] == "KSL-B3")
        assert [f["kind"] for f in flagged["data"]["flags"]] == ["canopy_loss"]


async def test_baseline_rejects_non_evidence_capture(gs):
    c = await seed(gs, {"KSL-A1": metrics()}, evidence_grade=False)
    r = await gs.http.post(f"{BASE}/baseline", json={"capture_id": c["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


async def test_capture_list_filters_and_zone_detail_history(gs):
    for _ in range(3):
        await seed(gs, {"KSL-C2": metrics()}, evidence_grade=True)
    await seed(gs, {"KSL-C2": metrics()}, evidence_grade=False)
    assert len((await gs.http.get(f"{BASE}/captures", params={"evidence_grade": True})).json()) == 3
    detail = (await gs.http.get(f"{BASE}/zones/KSL-C2")).json()
    assert len(detail["metrics_history"]) == 4


async def test_camera_status_reports_offline_with_since(gs):
    s = (await gs.http.get(f"{BASE}/camera/status")).json()
    assert s["online"] is False and s["locked"] is False
    assert s["since"] is not None  # ruling R2: never null


# ---- camera ------------------------------------------------------------------------------------
async def test_camera_settings_and_lock_persist_while_offline(gs):
    r = await gs.http.patch(f"{BASE}/camera/settings", json={"jpeg_quality": 20, "vflip": True})
    assert r.status_code == 200
    assert r.json()["desired"]["jpeg_quality"] == 20 and r.json()["desired"]["frame_size"] == "SVGA"
    r = await gs.http.post(f"{BASE}/camera/lock", json={"locked": True})
    # CameraStatus.locked is the effective lock: the camera has never confirmed it, so not locked.
    assert r.status_code == 200 and r.json()["locked"] is False
    s = (await gs.http.get(f"{BASE}/camera/status")).json()
    assert s["locked"] is False and s["desired"]["vflip"] is True and s["online"] is False
    assert gs.services.camera.locked is True  # the desired lock persists for the reconnect re-apply
    ui = (await gs.http.get(f"{BASE}/system/settings")).json()
    assert ui["camera_desired"]["jpeg_quality"] == 20  # one desired-settings record (L5)
    assert (await gs.http.post(f"{BASE}/camera/reconnect")).status_code == 202


# ---- calibration -------------------------------------------------------------------------------
async def test_calibration_offline_rules(gs):
    cal = (await gs.http.get(f"{BASE}/calibration")).json()
    assert cal["mode"] == "default" and cal["active"] is True
    r = await gs.http.get(f"{BASE}/calibration/frame.jpg")
    assert r.status_code == 409 and r.json()["error"]["code"] == "camera_offline"
    square = [[100, 100], [700, 100], [700, 500], [100, 500]]
    r = await gs.http.post(f"{BASE}/calibration/four-corner", json={"corners_px": square, "north_edge": 0})
    assert r.status_code == 409 and r.json()["error"]["code"] == "camera_offline"
    r = await gs.http.post(f"{BASE}/calibration/reset")
    assert r.status_code == 200
    body = r.json()
    assert body["calibration"]["mode"] == "default" and body["calibration"]["id"] != cal["id"]
    assert body["recommend"] == {"reset_baseline": True, "recommission": True}


async def test_four_corner_rejects_non_convex_corners(gs):
    dart = [[0, 0], [100, 0], [50, 10], [0, 100]]  # (50, 10) lies inside the other three
    r = await gs.http.post(f"{BASE}/calibration/four-corner", json={"corners_px": dart, "north_edge": 0})
    assert r.status_code == 422 and r.json()["error"]["code"] == "non_convex"
    r = await gs.http.post(f"{BASE}/calibration/four-corner", json={"corners_px": dart[:3], "north_edge": 0})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_corners"


# ---- captures, compare, media ------------------------------------------------------------------
async def test_capture_get_latest_and_unknown(gs):
    r = await gs.http.get(f"{BASE}/captures/latest")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    a = await seed(gs, {"KSL-A1": metrics()}, evidence_grade=True)
    gs.clock.advance(5)
    b = await seed(gs, {"KSL-A1": metrics()}, evidence_grade=False, trigger="interval")
    assert (await gs.http.get(f"{BASE}/captures/latest")).json()["id"] == b["id"]
    assert (await gs.http.get(f"{BASE}/captures/{a['id']}")).json()["is_baseline"] is True
    assert (await gs.http.get(f"{BASE}/captures/nope")).status_code == 404
    listed = (await gs.http.get(f"{BASE}/captures")).json()
    assert [c["id"] for c in listed] == [b["id"], a["id"]]  # newest first
    assert [
        c["id"] for c in (await gs.http.get(f"{BASE}/captures", params={"trigger": "interval"})).json()
    ] == [b["id"]]
    later = (await gs.http.get(f"{BASE}/captures", params={"from": b["taken_at"]})).json()
    assert [c["id"] for c in later] == [b["id"]]
    assert len((await gs.http.get(f"{BASE}/captures", params={"limit": 1})).json()) == 1
    assert (await gs.http.get(f"{BASE}/captures", params={"from": "yesterday"})).status_code == 422


async def test_seed_unknown_zone_is_422(gs):
    r = await gs.http.post(
        f"{BASE}/test/seed/capture", json={"zone_metrics": {"KSL-Z9": {}}, "evidence_grade": True}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


async def test_compare_deltas_and_change_map_for_seeded(gs):
    a = await seed(gs, {"KSL-B3": metrics(canopy_pct=60, vari_mean=0.4, dieback_pct=2)}, evidence_grade=True)
    b = await seed(
        gs,
        {"KSL-B3": metrics(canopy_pct=45, vari_mean=0.25, dieback_pct=10, new_growth_pct=1)},
        evidence_grade=True,
    )
    r = await gs.http.get(f"{BASE}/captures/compare", params={"a": a["id"], "b": b["id"]})
    assert r.status_code == 200
    cmp = r.json()
    assert cmp["a"] == a["id"] and cmp["b"] == b["id"]
    assert cmp["change_url"] == f"{BASE}/media/compare/{a['id']}/{b['id']}/change.png"
    z = next(z for z in cmp["zones"] if z["zone_id"] == "KSL-B3")
    assert z["canopy_pp"] == -15 and abs(z["vari"] - (-0.15)) < 1e-9
    assert z["dieback_pp"] == 8 and z["new_growth_pp"] == 1
    assert len(cmp["zones"]) == 25
    assert (await gs.http.get(cmp["change_url"])).status_code == 200  # synthetic ndvi files (ruling R22a)
    r = await gs.http.get(f"{BASE}/captures/compare", params={"a": a["id"], "b": "missing"})
    assert r.status_code == 404


async def test_media_for_seeded_capture_is_synthetic_and_live_is_404(gs):
    c = await seed(gs, {"KSL-A1": metrics()}, evidence_grade=True)
    for kind, url in c["media_urls"].items():
        r = await gs.http.get(url)  # ruling R22a: generated files, so the whole pipeline works in test mode
        assert r.status_code == 200, kind
    assert (await gs.http.get(f"{BASE}/media/captures/{c['id']}/thumbnail")).status_code == 404
    missing = await gs.http.get(f"{BASE}/media/captures/no-such-capture/image")
    assert missing.status_code == 404 and missing.json()["error"]["details"] is None
    r = await gs.http.get(f"{BASE}/media/live/latest.jpg")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# ---- zones -------------------------------------------------------------------------------------
async def test_zones_include_latest_metrics(gs):
    zones = (await gs.http.get(f"{BASE}/zones")).json()
    assert len(zones) == 25 and all(z["metrics"] is None for z in zones)
    await seed(gs, {"KSL-B3": metrics(canopy_pct=60)}, evidence_grade=True)
    gs.clock.advance(10)
    await seed(gs, {"KSL-B3": metrics(canopy_pct=50)}, evidence_grade=True)
    zones = {z["zone"]["id"]: z for z in (await gs.http.get(f"{BASE}/zones")).json()}
    assert zones["KSL-B3"]["metrics"]["canopy_pct"] == 50
    detail = (await gs.http.get(f"{BASE}/zones/KSL-B3")).json()
    assert [h["canopy_pct"] for h in detail["metrics_history"]] == [60, 50]  # chronological
    assert detail["metrics"]["canopy_pct"] == 50
    assert detail["last_capture_at"] == detail["metrics_history"][-1]["taken_at"]
    assert detail["covering_nodes"] == []
    r = await gs.http.get(f"{BASE}/zones/KSL-B3", params={"limit": 1})
    assert [h["canopy_pct"] for h in r.json()["metrics_history"]] == [50]
    assert (await gs.http.get(f"{BASE}/zones/KSL-Z9")).status_code == 404


# ---- test reset --------------------------------------------------------------------------------
async def test_reset_clears_captures_and_restores_state(gs):
    await seed(gs, {"KSL-A1": metrics()}, evidence_grade=True)
    await gs.http.post(f"{BASE}/calibration/reset")
    await gs.http.patch(f"{BASE}/camera/settings", json={"jpeg_quality": 30, "hmirror": True})
    await gs.http.post(f"{BASE}/camera/lock", json={"locked": True})
    await gs.http.post(f"{BASE}/test/clock/advance", json={"seconds": 3600})
    await gs.http.post(f"{BASE}/test/cloud/fail", json={"failing": True})
    assert (await gs.http.post(f"{BASE}/test/reset")).status_code == 200
    assert (await gs.http.get(f"{BASE}/captures")).json() == []
    cals = gs.services.repo.query("SELECT * FROM calibrations", table="calibrations")
    assert len(cals) == 1 and cals[0]["mode"] == "default" and cals[0]["active"] is True
    assert (await gs.http.get(f"{BASE}/calibration")).json()["id"] == cals[0]["id"]
    assert gs.clock.now() == T0
    cam = (await gs.http.get(f"{BASE}/camera/status")).json()
    assert cam["locked"] is False and cam["desired"] == {
        "frame_size": "SVGA",
        "jpeg_quality": 12,
        "vflip": False,
        "hmirror": False,
        "flash": False,
        "gain_ceiling": 2,
    }
    assert gs.cloud.failing is False
    sync = (await gs.http.get(f"{BASE}/system/status")).json()["sync"]
    # bookkeeping was reset; the worker may already have drained the re-seeded rows, on the reset clock (T0)
    assert sync["last_success_at"] in (None, "2026-10-16T03:04:05.123Z")
    # the capture service forgot its baseline: the next evidence-grade seed becomes the baseline
    c = await seed(gs, {"KSL-A1": metrics()}, evidence_grade=True)
    assert c["is_baseline"] is True


# ---- review fixes ------------------------------------------------------------------------------
def _bulk_captures(svc: Any, n: int) -> None:
    """n captures x every zone, written straight into SQLite (no outbox) to keep the test fast."""
    zones = [z.id for z in svc.site.zones()]
    cal = svc.calibration.active().id
    quality = '{"sharpness":120,"mean":128,"clipped_pct":0.5,"motion":false,"exposure_locked":true}'
    caps, zms = [], []
    for i in range(n):
        cid = f"bulk-{i:06d}"
        at = (T0 + timedelta(seconds=10 * i)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        caps.append(
            (cid, at, "interval", "esp32cam", '["R","G","B"]', cal, i, "{}", "local", quality, 1, 0, 0)
        )
        zms.extend((cid, z, float(i % 100), 20.0, 15.0, 5.0, 0.3, 0.2, 0.4, 0.0, 0.0, "[]") for z in zones)
    with svc.db.tx() as conn:
        conn.executemany(
            "INSERT INTO captures (id, taken_at, trigger, imagery_source, bands, calibration_id, frame_seq, "
            "media, media_state, quality, evidence_grade, is_baseline, flagged) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            caps,
        )
        conn.executemany(
            "INSERT INTO zone_metrics (capture_id, zone_id, canopy_pct, water_pct, mud_pct, other_pct, "
            "vari_mean, vari_p10, vari_p90, dieback_pct, new_growth_pct, flags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            zms,
        )


async def test_zone_routes_stay_fast_with_thousands_of_captures(gs):
    n = 3000
    _bulk_captures(gs.services, n)
    t = time.perf_counter()
    zones = (await gs.http.get(f"{BASE}/zones")).json()
    zones_s = time.perf_counter() - t
    t = time.perf_counter()
    detail = (await gs.http.get(f"{BASE}/zones/KSL-C3")).json()
    detail_s = time.perf_counter() - t
    assert zones_s < 0.5 and detail_s < 0.5, (zones_s, detail_s)
    assert all(z["metrics"]["canopy_pct"] == float((n - 1) % 100) for z in zones)
    hist = detail["metrics_history"]
    assert len(hist) == 200 and hist[-1]["canopy_pct"] == float((n - 1) % 100)
    assert hist == sorted(hist, key=lambda h: h["taken_at"])


def test_change_map_cache_survives_concurrent_writers(tmp_path, monkeypatch):
    svc = SimpleNamespace(data_root=tmp_path)
    monkeypatch.setattr(routes_media, "_media_path", lambda _svc, cid, kind: Path(f"{cid}-{kind}"))
    monkeypatch.setattr(routes_media, "change_map_png", lambda a, b: (time.sleep(0.05), b"png-bytes")[1])
    errors: list[BaseException] = []
    paths: list[Path] = []

    def worker() -> None:
        try:
            paths.append(routes_media._change_map(svc, "a", "b"))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == []
    assert len(set(paths)) == 1 and paths[0].read_bytes() == b"png-bytes"
    assert [p.name for p in paths[0].parent.iterdir()] == [paths[0].name]  # no temp files left behind
