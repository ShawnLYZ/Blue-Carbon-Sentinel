"""CaptureService (spec section 9; addendum A2, H2, H5, N7, N11, I4).

Triggers: an interval loop (every 10 s) and a change loop fed by the imagery stream; both pause
while the camera is offline. ``capture_now("manual")`` raises ``CameraOffline`` instead.

Every capture takes the sharpest of the last five site rasters, measures quality, classifies,
computes zone metrics against the baseline of the active calibration, evaluates zone flags,
decides baseline and cloud eligibility, writes the artefacts and rows, then emits
``capture.created``, ``zone.metrics``, ``zone.flagged`` (per flagged zone) and ``baseline.updated``.
Analysis and storage run in a worker thread, one capture at a time.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import cv2
import numpy as np
from bcs_protocol.timefmt import to_iso

from bcs_gs.api.errors import ApiError
from bcs_gs.api.models import Capture, CaptureQuality, ZoneMetrics
from bcs_gs.capture.artefacts import BUCKET, CONTENT_TYPES, decode_indexed_png, indexed_png, write_artefacts
from bcs_gs.capture.payloads import capture_events, to_capture
from bcs_gs.capture.quality import is_evidence_grade, pick_sharpest, quality_metrics, should_become_baseline
from bcs_gs.capture.synthetic import synthetic_artefacts
from bcs_gs.capture.triggers import ChangeTrigger, cloud_eligible, frame_difference, is_unchanged
from bcs_gs.core.config import Thresholds
from bcs_gs.core.ids import uuid7
from bcs_gs.reality.fallback import fallback_heights
from bcs_gs.reality.quality import to_height_u16
from bcs_gs.vegetation import (
    BaselineRef,
    ZoneMetricsRow,
    baseline_ref_from,
    classify_raster,
    evaluate_flags,
    vari,
    zone_metrics,
)

log = logging.getLogger("bcs_gs.capture")

INTERVAL_S = 10.0
RECENT_N = 5
CHANGE_RETRY_S = 1.0

# seed_capture (I4): values for metric fields the caller leaves out.
SEED_DEFAULTS: dict[str, Any] = {
    "canopy_pct": 60.0, "water_pct": 20.0, "mud_pct": 15.0, "other_pct": 5.0,
    "vari_mean": 0.30, "vari_p10": 0.20, "vari_p90": 0.40, "canopy_loss_pp": None, "vari_drop": None,
    "dieback_pct": 0.0, "new_growth_pct": 0.0, "discolouration": None,
}  # fmt: skip
SEED_QUALITY = {
    True: {"sharpness": 120.0, "mean": 128.0, "clipped_pct": 0.5, "motion": False, "exposure_locked": True},
    False: {"sharpness": 20.0, "mean": 128.0, "clipped_pct": 0.5, "motion": False, "exposure_locked": True},
}
_METRIC_FIELDS = set(ZoneMetrics.model_fields) - {"zone_id", "flags"}
# Fields that depend only on the capture's own class map; restated when it becomes the baseline.
_CLASS_FIELDS = ("canopy_pct", "water_pct", "mud_pct", "other_pct", "vari_mean", "vari_p10", "vari_p90")


class CameraOffline(ApiError):
    def __init__(self) -> None:
        super().__init__("camera_offline", 409, "The camera is offline; no capture was taken.")


class BaselineConflict(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__("conflict", 409, message)


class CaptureNotFound(ApiError):
    def __init__(self, capture_id: str) -> None:
        super().__init__("not_found", 404, f"Capture {capture_id} not found.")


@dataclass
class _Result:
    capture: Capture
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


class CaptureService:
    def __init__(
        self,
        *,
        repo: Any,
        media: Any,
        bus: Any,
        clock: Any,
        imagery: Any,
        camera: Any,
        calibration: Any,
        reality: Any,
        site: Any,
        thresholds: Thresholds,
        test_mode: bool = False,
    ) -> None:
        self.repo, self.media, self.bus, self.clock = repo, media, bus, clock
        self.imagery, self.camera, self.calibration, self.reality = imagery, camera, calibration, reality
        self.site, self.cfg, self.test_mode = site, thresholds, test_mode
        mo = thresholds.motion
        self.trigger = ChangeTrigger(mo.motion_threshold, mo.change_threshold, mo.stable_s)
        self._diff = {"size": int(mo.diff_size_px), "sigma": float(mo.diff_blur_sigma)}
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self._last_rgb: np.ndarray | None = None  # raster of the last real capture (N7 change score)
        self._sent_minute: str | None = (
            None  # UTC minute whose first unchanged interval capture was sent (A2)
        )
        self._recent_rgb: OrderedDict[str, np.ndarray] = OrderedDict()  # capture id -> raster
        self._baseline_loaded = False
        self._baseline_row: dict[str, Any] | None = None
        self._baseline_ref: BaselineRef | None = None  # pixel reference; None for a seeded baseline
        self._baseline_metrics: dict[str, ZoneMetrics] | None = None

    # ---- lifecycle --------------------------------------------------------------------------
    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._interval_loop(), name="capture-interval"),
            asyncio.create_task(self._change_loop(), name="capture-change"),
        ]

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    def reset(self) -> None:
        """Forget cached state (test reset: the store was cleared underneath)."""
        self.trigger = ChangeTrigger(
            self.trigger.motion_threshold, self.trigger.change_threshold, self.trigger.stable_s
        )
        self._last_rgb = None
        self._sent_minute = None
        self._recent_rgb.clear()
        self._baseline_loaded = False
        self._baseline_row = self._baseline_ref = self._baseline_metrics = None

    def _online(self) -> bool:
        try:
            return bool(self.imagery.online())
        except Exception:  # noqa: BLE001
            return False

    async def _interval_loop(self) -> None:
        while True:
            await self.clock.sleep(INTERVAL_S)
            if not self._online():
                continue  # paused while the camera is offline (spec section 6)
            try:
                await self.capture_now("interval")
            except CameraOffline:
                pass
            except Exception as exc:  # noqa: BLE001
                log.warning("interval capture failed: %s", type(exc).__name__)

    async def _change_loop(self) -> None:
        while True:
            try:
                prev: np.ndarray | None = None
                async for r in self.imagery.subscribe():
                    rgb = r.image[..., :3]
                    diff_prev = 0.0 if prev is None else frame_difference(prev, rgb, **self._diff)
                    prev = rgb
                    last = self._last_rgb
                    diff_last = 0.0 if last is None else frame_difference(last, rgb, **self._diff)
                    due = self.trigger.observe(diff_prev, diff_last, r.captured_at)
                    if due and not self._lock.locked() and self._online():
                        try:
                            await self.capture_now("change")
                        except CameraOffline:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("change trigger loop failed: %s", type(exc).__name__)
            await self.clock.sleep(CHANGE_RETRY_S)

    def _publish(self, events: list[tuple[str, dict[str, Any]]]) -> None:
        for type_, data in events:
            self.bus.publish(type_, data)

    # ---- public API -------------------------------------------------------------------------
    async def capture_now(self, trigger: str = "manual") -> Capture:
        """Take a capture now. Raises ``CameraOffline`` without a live camera."""
        if trigger not in ("interval", "change", "manual"):
            raise ValueError(f"unknown trigger {trigger!r}")
        async with self._lock:
            if not self._online():
                raise CameraOffline()
            rasters = list(self.imagery.recent(RECENT_N))
            if not rasters:
                latest = self.imagery.latest()
                rasters = [latest] if latest is not None else []
            if not rasters:
                raise CameraOffline()
            newest = max(r.captured_at for r in rasters)
            moving = not self.trigger.settled(newest)  # Review Focus 2: motion until stable >= 2 s
            locked = bool(self.camera.status().locked)
            result = await asyncio.to_thread(self._capture_sync, rasters, trigger, moving, locked)
        self._publish(result.events)
        return result.capture

    async def seed_capture(
        self,
        zone_metrics: dict[str, dict[str, Any]],
        evidence_grade: bool,
        quality: dict[str, Any] | None = None,
        trigger: str = "manual",
    ) -> Capture:
        """Test mode only (addendum I4): a capture from numbers, no media, then the same pipeline."""
        if not self.test_mode:
            raise PermissionError("seed_capture is available in test mode only")
        async with self._lock:
            result = await asyncio.to_thread(self._seed_sync, zone_metrics, evidence_grade, quality, trigger)
        self._publish(result.events)
        return result.capture

    async def set_baseline(self, capture_id: str | None = None) -> Capture:
        """Make ``capture_id`` (default: the latest evidence-grade capture) the baseline."""
        async with self._lock:
            result = await asyncio.to_thread(self._set_baseline_sync, capture_id)
        self._publish(result.events)
        return result.capture

    def baseline(self) -> Capture | None:
        rows = self.repo.query(
            "SELECT * FROM captures WHERE is_baseline = 1 ORDER BY taken_at DESC LIMIT 1", table="captures"
        )
        return to_capture(rows[0], self._stored_metrics(rows[0]["id"])) if rows else None

    def mark_referenced(self, capture_id: str, reason: str = "referenced") -> None:
        """A2 / H7: a capture a forecast or plan builds on is kept and sent to the cloud. Its row and metrics
        are (re-)enqueued, its media promoted and protected. ``reason`` (``referenced``, or
        ``plan_application`` for a plan's capture at application) is recorded when the capture has no
        reason yet or only ``referenced``; ``baseline`` and other reasons are kept. Blocking: call it from
        a worker thread."""
        row = self.repo.get("captures", {"id": capture_id})
        if row is None:
            raise CaptureNotFound(capture_id)
        if not row["retention_reason"] or row["retention_reason"] == "referenced":
            row["retention_reason"] = reason
        with self.repo.transaction():
            self.repo.upsert("captures", row, sync=True)
            for m in self._stored_metrics(capture_id):
                self.repo.upsert(
                    "zone_metrics", ZoneMetricsRow(**m.model_dump()).to_row(capture_id), sync=True
                )
        keys = list((row.get("media") or {}).values())
        self.media.promote(BUCKET, keys)
        self.media.set_protected(BUCKET, keys, True)

    def latest_class_map(self) -> tuple[str, np.ndarray] | None:
        """(capture ID, class codes) of the latest evidence-grade capture that has a class map on disk
        (seeded captures have none). Blocking: call it from a worker thread."""
        rows = self.repo.query(
            "SELECT * FROM captures WHERE evidence_grade = 1 ORDER BY taken_at DESC, id DESC LIMIT 50",
            table="captures",
        )
        for row in rows:
            key = (row.get("media") or {}).get("classes")
            if not key:
                continue
            path = self.media.path(BUCKET, key)
            if not path.exists():
                continue
            try:
                return row["id"], decode_indexed_png(path.read_bytes())
            except (ValueError, OSError) as exc:
                log.warning("class map of %s unreadable: %s", row["id"], exc)
        return None

    def get(self, capture_id: str) -> Capture | None:
        row = self.repo.get("captures", {"id": capture_id})
        return None if row is None else to_capture(row, self._stored_metrics(capture_id))

    # ---- capture pipeline (worker thread) ---------------------------------------------------
    def _capture_sync(self, rasters: list[Any], trigger: str, moving: bool, locked: bool) -> _Result:
        self._ensure_baseline_loaded()
        raster = pick_sharpest(rasters)
        rgb = np.ascontiguousarray(raster.image[..., :3], np.uint8)
        cal_id = raster.calibration_id or self.calibration.active().id
        q = quality_metrics(rgb, moving, locked)
        change = None if self._last_rgb is None else frame_difference(self._last_rgb, rgb, **self._diff)
        ref, base_metrics = self._comparison(cal_id)
        classes = classify_raster(rgb, ref.exg_threshold if ref else None, self.cfg)
        metrics = zone_metrics(rgb, classes, ref, self.cfg, registry=self.site)
        if ref is None and base_metrics:
            for z, row in metrics.items():  # metrics-only baseline: no pixel masks
                b = base_metrics.get(z)
                if b is not None:
                    row.canopy_loss_pp = b.canopy_pct - row.canopy_pct
                    row.vari_drop = _sub(b.vari_mean, row.vari_mean)
        vari_img = vari(rgb)
        return self._commit(
            taken_at=raster.captured_at, trigger=trigger, source=raster.source_id, bands=list(raster.bands),
            cal_id=cal_id, frame_seq=int(raster.seq), quality=q, evidence_grade=is_evidence_grade(q, self.cfg),
            change_score=change, metrics=metrics, pixels=(rgb, self._height(rgb), classes, vari_img),
        )  # fmt: skip

    def _height(self, rgb: np.ndarray) -> np.ndarray:
        frame = self.reality.latest() if self.reality is not None else None
        if frame is not None and getattr(frame, "height_u16", None) is not None:
            return frame.height_u16
        return to_height_u16(fallback_heights(rgb, self.cfg))

    def _seed_sync(
        self,
        given: dict[str, dict[str, Any]],
        evidence_grade: bool,
        quality: dict[str, Any] | None,
        trigger: str,
    ) -> _Result:
        if trigger not in ("interval", "change", "manual"):
            raise ValueError(f"unknown trigger {trigger!r}")
        self._ensure_baseline_loaded()
        zones = [z.id for z in self.site.zones()]
        unknown = set(given) - set(zones)
        if unknown:
            raise ValueError(f"unknown zone ids: {sorted(unknown)}")
        cal_id = self.calibration.active().id
        _, base_metrics = self._comparison(cal_id)
        metrics: dict[str, ZoneMetricsRow] = {}
        for z in zones:
            values = {k: v for k, v in (given.get(z) or {}).items() if k not in ("zone_id", "flags")}
            bad = set(values) - _METRIC_FIELDS
            if bad:
                raise ValueError(f"unknown metric fields for {z}: {sorted(bad)}")
            data = {**SEED_DEFAULTS, **values, "zone_id": z}
            b = (base_metrics or {}).get(z)
            if b is not None:  # derive the baseline comparisons the caller did not give
                if "canopy_loss_pp" not in values:
                    data["canopy_loss_pp"] = b.canopy_pct - data["canopy_pct"]
                if "vari_drop" not in values:
                    data["vari_drop"] = _sub(b.vari_mean, data["vari_mean"])
            metrics[z] = ZoneMetricsRow.model_validate(data)
        q = CaptureQuality.model_validate({**SEED_QUALITY[bool(evidence_grade)], **(quality or {})})
        return self._commit(
            taken_at=self.clock.now(), trigger=trigger, source=getattr(self.imagery, "source_id", "esp32cam"),
            bands=["R", "G", "B"], cal_id=cal_id, frame_seq=0, quality=q, evidence_grade=bool(evidence_grade),
            change_score=None, metrics=metrics, pixels=None,
            synthetic=synthetic_artefacts(metrics, self.site),  # R22a: test-mode media
        )  # fmt: skip

    def _commit(
        self,
        *,
        taken_at: datetime,
        trigger: str,
        source: str,
        bands: list[str],
        cal_id: str,
        frame_seq: int,
        quality: CaptureQuality,
        evidence_grade: bool,
        change_score: float | None,
        metrics: dict[str, ZoneMetricsRow],
        pixels: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None,
        synthetic: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None,
    ) -> _Result:
        has_baseline = self._baseline_row is not None and self._baseline_row["calibration_id"] == cal_id
        becomes = should_become_baseline(evidence_grade, has_baseline)
        new_ref: BaselineRef | None = None
        if becomes and pixels is not None:
            # Classify the new baseline with its own threshold, as every later capture will be.
            rgb, height, _, vari_img = pixels
            new_ref = baseline_ref_from(rgb, self.cfg, registry=self.site)
            pixels = (rgb, height, self._restate(rgb, new_ref, metrics), vari_img)
        for row in metrics.values():
            row.flags = evaluate_flags(row, None, self.cfg)  # plan application arrives in M5
        flagged = any(row.flags for row in metrics.values())
        minute = to_iso(taken_at)[:16]
        eligible = cloud_eligible(
            trigger, flagged, becomes, False, change_score, self._sent_minute == minute,
            change_threshold=self.cfg.motion.change_threshold,
        )  # fmt: skip
        cap_id = uuid7()
        keys: dict[str, str] = {}
        media_pixels = pixels if pixels is not None else synthetic  # synthetic: files only (R22a)
        if media_pixels is not None:
            rgb, height, classes, vari_img = media_pixels
            keys = write_artefacts(
                self.media, cap_id, taken_at, rgb, height, classes, vari_img, eligible, protected=becomes
            )
        row = {
            "id": cap_id, "taken_at": to_iso(taken_at), "trigger": trigger, "imagery_source": source,
            "bands": bands, "calibration_id": cal_id, "frame_seq": frame_seq, "media": keys,
            "media_state": "local", "quality": quality.model_dump(), "evidence_grade": evidence_grade,
            "is_baseline": becomes, "flagged": flagged, "change_score": change_score,
            "retention_reason": "baseline" if becomes else None,
        }  # fmt: skip
        release: list[str] = []
        with self.repo.transaction():
            if becomes:
                release = self._clear_previous_baseline()
            self.repo.insert("captures", row, sync=eligible)
            for m in metrics.values():
                self.repo.insert("zone_metrics", m.to_row(cap_id), sync=eligible)
        self.media.set_protected(BUCKET, release, False)
        unchanged = is_unchanged(change_score, self.cfg.motion.change_threshold)
        if eligible and trigger == "interval" and not (flagged or becomes) and unchanged:
            self._sent_minute = minute  # sent under A2's first-unchanged-interval-capture-per-minute rule
        if pixels is not None:
            self._last_rgb = pixels[0]
            self._remember(cap_id, pixels[0])
        if becomes:
            self._install_baseline(row, metrics, pixels[0] if pixels is not None else None, new_ref)
        capture = to_capture(row, list(metrics.values()))
        return _Result(capture, capture_events(capture, metrics, becomes))

    # ---- baseline -----------------------------------------------------------------------------
    def _comparison(self, cal_id: str) -> tuple[BaselineRef | None, dict[str, ZoneMetrics] | None]:
        """The baseline to compare with: only one taken under the same calibration."""
        if self._baseline_row is None or self._baseline_row["calibration_id"] != cal_id:
            return None, None
        return self._baseline_ref, self._baseline_metrics

    def _ensure_baseline_loaded(self) -> None:
        if self._baseline_loaded:
            return
        rows = self.repo.query(
            "SELECT * FROM captures WHERE is_baseline = 1 ORDER BY taken_at DESC LIMIT 1", table="captures"
        )
        if rows:
            row = rows[0]
            stored = {m.zone_id: m for m in self._stored_metrics(row["id"])}
            self._install_baseline(row, stored, self._load_rgb(row))
        self._baseline_loaded = True

    def _install_baseline(
        self,
        row: dict[str, Any],
        metrics: dict[str, Any],
        rgb: np.ndarray | None,
        ref: BaselineRef | None = None,
    ) -> None:
        self._baseline_row = dict(row)
        self._baseline_metrics = {z: ZoneMetrics.model_validate(m.model_dump()) for z, m in metrics.items()}
        if ref is None and rgb is not None:
            ref = baseline_ref_from(rgb, self.cfg, registry=self.site)
        self._baseline_ref = ref
        self._baseline_loaded = True

    def _restate(self, rgb: np.ndarray, ref: BaselineRef, metrics: dict[str, Any]) -> np.ndarray:
        """Re-classify the baseline raster with the baseline's own ExG threshold (Otsu, floored at
        the pre-baseline default) and overwrite the class-derived fields of ``metrics`` in place, so
        the baseline's stored canopy uses the same threshold as every capture compared with it.
        Comparison fields (loss, drop, dieback, growth, discolouration) are kept as recorded.
        Returns the new class map."""
        classes = classify_raster(rgb, ref.exg_threshold, self.cfg)
        fresh = zone_metrics(rgb, classes, None, self.cfg, registry=self.site)
        for z, m in metrics.items():
            f = fresh.get(z)
            if f is not None:
                for name in _CLASS_FIELDS:
                    setattr(m, name, getattr(f, name))
        return classes

    def _clear_previous_baseline(self) -> list[str]:
        """Inside the caller's transaction: unflag every current baseline; returns media keys to release."""
        release: list[str] = []
        for old in self.repo.query("SELECT * FROM captures WHERE is_baseline = 1", table="captures"):
            old["is_baseline"] = False
            if old["retention_reason"] == "baseline":
                old["retention_reason"] = None
            self.repo.upsert("captures", old, sync=True)
            release.extend((old["media"] or {}).values())
        return release

    def _set_baseline_sync(self, capture_id: str | None) -> _Result:
        self._ensure_baseline_loaded()
        if capture_id is None:
            rows = self.repo.query(
                "SELECT * FROM captures WHERE evidence_grade = 1 ORDER BY taken_at DESC LIMIT 1",
                table="captures",
            )
            if not rows:
                raise BaselineConflict("There is no evidence-grade capture to make the baseline.")
            row = rows[0]
        else:
            got = self.repo.get("captures", {"id": capture_id})
            if got is None:
                raise CaptureNotFound(capture_id)
            row = got
        if not row["evidence_grade"]:
            raise BaselineConflict("Only an evidence-grade capture can be the baseline.")
        metrics = self._stored_metrics(row["id"])
        rgb = self._load_rgb(row)
        ref = None if rgb is None else baseline_ref_from(rgb, self.cfg, registry=self.site)
        if not row["is_baseline"]:
            row["is_baseline"] = True
            row["retention_reason"] = "baseline"
            classes_key = (row.get("media") or {}).get("classes")
            staged = None
            if ref is not None and rgb is not None:
                by_zone = {m.zone_id: m for m in metrics}
                classes = self._restate(rgb, ref, by_zone)
                if classes_key:  # the stored class map now matches the restated metrics
                    if row["media_state"] == "uploaded":
                        row["media_state"] = "local"  # the new class map is not in the cloud yet
                    # Staged beside the live file: the database change commits first, then the rename,
                    # so a failed transaction leaves the old class map in place and in agreement.
                    staged = self.media.stage(BUCKET, classes_key, indexed_png(classes))
            try:
                with self.repo.transaction():
                    release = [k for k in self._clear_previous_baseline() if k not in row["media"].values()]
                    # A baseline is cloud-eligible: (re-)enqueue its row and metrics, then its media.
                    self.repo.upsert("captures", row, sync=True)
                    for m in metrics:
                        self.repo.upsert(
                            "zone_metrics", ZoneMetricsRow(**m.model_dump()).to_row(row["id"]), sync=True
                        )
            except BaseException:
                if staged is not None:
                    self.media.discard(staged)
                raise
            if staged is not None:
                self.media.put_staged(
                    BUCKET, classes_key, staged, CONTENT_TYPES["classes"], protected=True, cloud=True
                )
            self.media.set_protected(BUCKET, release, False)
        keys = list((row["media"] or {}).values())
        self.media.promote(BUCKET, keys)
        self.media.set_protected(BUCKET, keys, True)
        self._install_baseline(row, {m.zone_id: m for m in metrics}, rgb, ref)
        capture = to_capture(row, metrics)
        return _Result(capture, [("baseline.updated", {"capture_id": row["id"]})])

    # ---- helpers ------------------------------------------------------------------------------
    def _remember(self, capture_id: str, rgb: np.ndarray) -> None:
        self._recent_rgb[capture_id] = rgb
        while len(self._recent_rgb) > RECENT_N:
            self._recent_rgb.popitem(last=False)

    def _load_rgb(self, row: dict[str, Any]) -> np.ndarray | None:
        """The capture's site raster: in memory for recent captures, else decoded from image.jpg."""
        if row["id"] in self._recent_rgb:
            return self._recent_rgb[row["id"]]
        key = (row.get("media") or {}).get("image")
        if not key:
            return None
        path = self.media.path(BUCKET, key)
        if not path.exists():
            return None
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        return None if bgr is None else cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    def _stored_metrics(self, capture_id: str) -> list[ZoneMetrics]:
        rows = self.repo.query(
            "SELECT * FROM zone_metrics WHERE capture_id = ?", (capture_id,), table="zone_metrics"
        )
        order = {z.id: i for i, z in enumerate(self.site.zones())}
        rows.sort(key=lambda r: order.get(r["zone_id"], len(order)))
        return [ZoneMetrics.model_validate({k: v for k, v in r.items() if k != "capture_id"}) for r in rows]
