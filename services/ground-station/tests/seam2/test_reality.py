"""RealityLayer (Task 7): pure height functions, the colour-class fallback and the worker hand-off.

Generated arrays only. The depth model is replaced by a stub object with ``available``/``infer``.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from bcs_gs.camera.imagery import SiteRaster
from bcs_gs.core.config import load_settings
from bcs_gs.core.events import EventBus
from bcs_gs.reality import (
    DepthRunner,
    RealityLayer,
    dynamic_range01,
    ema,
    fallback_heights,
    normalise_robust,
    quality_score,
    stability,
    to_height_u16,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SETTINGS = load_settings(REPO_ROOT, env_file=None)
T0 = datetime(2026, 10, 8, 3, 0, 0, tzinfo=UTC)


# ---- pure functions (brief Step 1) ----------------------------------------------------------
def test_normalise_robust_clips_outliers_to_unit_range():
    d = np.linspace(0, 1, 10000).reshape(100, 100).astype(np.float32)
    d[0, 0] = 1000
    n = normalise_robust(d)
    assert n.min() == 0 and n.max() == 1 and n[50, 50] == pytest.approx(0.5, abs=0.02)


def test_normalise_robust_flat_input_is_finite_zero():
    n = normalise_robust(np.full((10, 10), 3.0, np.float32))
    assert np.isfinite(n).all() and float(n.max()) == 0.0


def test_ema_alpha_point_three():
    assert np.allclose(ema(np.zeros((2, 2)), np.ones((2, 2))), 0.3) and np.allclose(
        ema(None, np.ones((2, 2))), 1
    )


def test_height_u16_shape_and_range():
    h = to_height_u16(np.random.default_rng(1).random((518, 518)).astype(np.float32))
    assert h.shape == (256, 256) and h.dtype == np.uint16 and h.max() <= 65535


def test_height_u16_maps_unit_range_to_full_scale():
    assert int(to_height_u16(np.ones((518, 518), np.float32)).min()) == 65535
    assert int(to_height_u16(np.zeros((518, 518), np.float32)).max()) == 0


def test_quality_weights():
    assert quality_score(1.0, 1.0, True) == pytest.approx(1.0)
    assert quality_score(0.2, 0.2, False) == pytest.approx(0.16)


def test_dynamic_range_and_stability_definitions():
    assert dynamic_range01(np.full((20, 20), 5.0, np.float32)) == pytest.approx(0.0)
    assert dynamic_range01(np.linspace(0, 10, 400, dtype=np.float32).reshape(20, 20)) == pytest.approx(
        0.96 / 0.98, abs=0.01
    )
    a = np.zeros((4, 4), np.float32)
    assert (
        stability(None, a) == 0.0 and stability(a, a) == 1.0 and stability(a, a + 0.25) == pytest.approx(0.75)
    )


def test_fallback_orders_canopy_above_mud_above_water():
    img = np.zeros((512, 512, 3), np.uint8)
    img[:, :170] = (40, 160, 40)
    img[:, 170:340] = (120, 90, 60)
    img[:, 340:] = (30, 60, 110)  # RGB patches
    h = fallback_heights(img)
    # Output is 256 x 256 (brief: blur "at 256"), so the brief's 512-px probe columns 80/255/450
    # become 40/127/225 and row 256 becomes 128: the centres of the same three patches.
    assert h.shape == (256, 256)
    assert h[128, 40] > h[128, 127] > h[128, 225]


def test_fallback_on_scene_without_canopy_is_flat_but_valid():  # Review Focus 4
    h = fallback_heights(np.full((512, 512, 3), 128, np.uint8))
    assert np.isfinite(h).all() and h.std() < 0.01


def test_depth_runner_without_weights_is_unavailable(tmp_path):
    r = DepthRunner(tmp_path / "missing")
    assert not r.available and r.provider is None


# ---- worker ---------------------------------------------------------------------------------
def _raster(seq: int, value: int = 128, *, cal: str = "cal-1", at_s: float = 0.0) -> SiteRaster:
    return SiteRaster(
        image=np.full((512, 512, 3), value, np.uint8), bands=("R", "G", "B"),
        captured_at=T0 + timedelta(seconds=at_s), source_id="esp32cam", seq=seq, calibration_id=cal,
    )  # fmt: skip


GRADIENT = np.tile(np.linspace(1.0, 2.0, 518, dtype=np.float32), (518, 1))


class StubDepth:
    """Stand-in for DepthRunner: ``infer`` returns ``self.out`` and can be held on a gate."""

    provider = "StubProvider"

    def __init__(self, out: np.ndarray = GRADIENT, available: bool = True) -> None:
        self.available = available
        self.out = out
        self.calls: list[int] = []
        self.gate: threading.Event | None = None
        self.entered = threading.Event()
        self.fail = False

    def infer(self, rgb512: np.ndarray) -> np.ndarray:
        self.calls.append(int(rgb512[0, 0, 0]))
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(5)
        if self.fail:
            raise RuntimeError("stub inference failure")
        return self.out


def _wait(cond, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.005)


def _layer(depth: StubDepth) -> tuple[RealityLayer, list[str]]:
    layer = RealityLayer(None, depth, EventBus(), SETTINGS)
    modes: list[str] = []
    layer.on_mode_change(modes.append)
    return layer, modes


def test_worker_processes_only_the_newest_raster_latest_wins():
    depth = StubDepth()
    depth.gate = threading.Event()
    layer, _ = _layer(depth)
    layer.start()
    try:
        layer.submit(_raster(1, value=10))
        assert depth.entered.wait(5)  # frame 1 is in inference, holding the worker
        for seq in (2, 3, 4):
            layer.submit(_raster(seq, value=10 * seq))
        depth.gate.set()
        _wait(lambda: (f := layer.latest()) is not None and f.frame_seq == 4)
        time.sleep(0.05)
        assert depth.calls == [10, 40]  # rasters 2 and 3 were replaced before the worker took them
        assert layer.dropped == 2
        f = layer.latest()
        assert f is not None and f.seq == 2 and f.calibration_id == "cal-1" and f.captured_at == T0
        assert f.height_u16.shape == (256, 256) and f.height_u16.dtype == np.uint16
        assert f.raster_rgb.shape == (512, 512, 3) and f.processed_at.tzinfo is not None
    finally:
        layer.stop()


def test_mode_follows_quality_and_availability_and_reports_changes():
    flat = (5.0 + np.random.default_rng(0).random((518, 518)) * 1e-4).astype(np.float32)
    depth = StubDepth(out=flat)
    layer, modes = _layer(depth)
    layer.start()
    try:
        layer.submit(_raster(1))  # no dynamic range: quality 0.2 < 0.35 although the model ran
        _wait(lambda: layer.latest() is not None)
        f1 = layer.latest()
        assert f1.mode == "fallback" and f1.quality == pytest.approx(0.2, abs=0.01)

        depth.out = GRADIENT
        layer.submit(_raster(2))
        _wait(lambda: layer.latest().frame_seq == 2)
        f2 = layer.latest()
        assert f2.mode == "depth" and f2.quality >= 0.35

        depth.available = False
        layer.submit(_raster(3))
        _wait(lambda: layer.latest().frame_seq == 3)
        f3 = layer.latest()
        assert f3.mode == "fallback" and f3.quality == 0.0 and len(depth.calls) == 2

        depth.available, depth.fail = True, True
        layer.submit(_raster(4))
        _wait(lambda: layer.latest().frame_seq == 4)
        assert layer.latest().mode == "fallback"  # an inference error never kills the worker
        _wait(lambda: len(modes) == 3)
        assert modes == ["fallback", "depth", "fallback"]  # one callback per change, not per frame
        assert layer.mode == "fallback" and layer.fps > 0
    finally:
        layer.stop()


def test_ema_carries_across_a_mode_switch():
    depth = StubDepth()
    layer, _ = _layer(depth)
    layer.start()
    try:
        layer.submit(_raster(1))
        _wait(lambda: layer.latest() is not None)
        first = layer.latest().height_u16.astype(np.float64)
        depth.available = False
        layer.submit(_raster(2))  # grey scene: fallback is flat
        _wait(lambda: layer.latest().frame_seq == 2)
        second = layer.latest().height_u16.astype(np.float64)
        # 70 % of the previous (gradient) surface survives the switch: it has not jumped flat
        assert second[:, -10:].mean() - second[:, :10].mean() > 0.5 * (
            first[:, -10:].mean() - first[:, :10].mean()
        )
    finally:
        layer.stop()


def _relief(frame) -> float:
    """East-minus-west mean of the u16 height map: the gradient stub's surface, ~0 when flat."""
    h = frame.height_u16.astype(np.float64)
    return float(h[:, -10:].mean() - h[:, :10].mean())


def test_calibration_change_resets_ema_and_stability():
    depth = StubDepth()
    layer, _ = _layer(depth)
    f1 = layer.process(_raster(1))
    same = layer.process(_raster(2))
    assert same.quality == pytest.approx(f1.quality + 0.3, abs=1e-3)  # stability 1 within a calibration
    moved = layer.process(_raster(3, cal="cal-2"))
    assert moved.calibration_id == "cal-2"
    assert moved.quality == pytest.approx(f1.quality, abs=1e-3)  # no stability across two warps
    depth.available = False
    layer.process(_raster(4, cal="cal-1"))  # recalibrated again: the grey fallback is not blended
    flat = layer.process(_raster(5, cal="cal-3"))
    assert _relief(flat) == pytest.approx(0.0, abs=1.0)


def test_calibration_change_does_not_blend_the_old_surface():
    depth = StubDepth()
    layer, _ = _layer(depth)
    assert _relief(layer.process(_raster(1))) > 30000
    depth.available = False
    carried = layer.process(_raster(2))  # same calibration: 70 % of the gradient carries over
    assert _relief(carried) > 15000
    layer2, _ = _layer(StubDepth())
    layer2.process(_raster(1))
    layer2._depth.available = False
    assert _relief(layer2.process(_raster(2, cal="cal-2"))) == pytest.approx(0.0, abs=1.0)


def test_capture_gap_over_three_seconds_resets_but_a_short_gap_does_not():
    depth = StubDepth()
    layer, _ = _layer(depth)
    f1 = layer.process(_raster(1, at_s=0.0))
    near = layer.process(_raster(2, at_s=2.5))
    assert near.quality == pytest.approx(f1.quality + 0.3, abs=1e-3)
    after_gap = layer.process(_raster(3, at_s=6.0))  # camera was offline > 3 s
    assert after_gap.quality == pytest.approx(f1.quality, abs=1e-3)
    depth.available = False
    assert _relief(layer.process(_raster(4, at_s=6.2))) > 15000  # carried within the session
    assert _relief(layer.process(_raster(5, at_s=10.0))) == pytest.approx(0.0, abs=1.0)


def test_start_resets_the_smoothing_state():
    depth = StubDepth()
    layer, _ = _layer(depth)
    layer.process(_raster(1))
    layer.start()
    layer.stop()
    depth.available = False
    assert _relief(layer.process(_raster(2))) == pytest.approx(0.0, abs=1.0)


class QueueImagery:
    def __init__(self) -> None:
        self.q: asyncio.Queue[SiteRaster | None] = asyncio.Queue()

    async def subscribe(self):
        while (r := await self.q.get()) is not None:
            yield r


async def test_layer_consumes_imagery_and_feeds_subscribers():
    imagery = QueueImagery()
    layer = RealityLayer(imagery, StubDepth(), EventBus(), SETTINGS)
    layer.start()
    try:
        sub = layer.subscribe()
        nxt = asyncio.ensure_future(sub.__anext__())
        await asyncio.sleep(0)
        await imagery.q.put(_raster(7))
        frame = await asyncio.wait_for(nxt, 5)
        assert frame.frame_seq == 7 and frame.mode == "depth"
        await sub.aclose()
    finally:
        await asyncio.to_thread(layer.stop)


async def test_services_have_a_reality_layer_that_is_idle_in_test_mode(gs):
    reality = gs.services.reality
    assert reality is not None and reality.latest() is None
    r = await gs.http.get("/api/v1/system/status")
    assert r.status_code == 200 and r.json()["depth"]["mode"] == "off"
