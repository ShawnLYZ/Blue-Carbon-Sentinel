from datetime import UTC, datetime

import cv2
import numpy as np
import pytest
from bcs_gs.core.clock import ManualClock
from bcs_gs.site.calibration import (
    CalibrationError,
    CalibrationService,
    default_homography,
    normalise_corners,
)
from bcs_gs.store.db import Database
from bcs_gs.store.repo import Repo

SQ = [(100, 100), (500, 120), (480, 500), (90, 470)]


def apply_h(H, p):
    v = H @ np.array([p[0], p[1], 1.0])
    return v[:2] / v[2]


class Events:
    def __init__(self):
        self.items = []

    def publish(self, type, data):
        self.items.append((type, data))

    def count(self, type):
        return sum(1 for t, _ in self.items if t == type)


class Ticking(ManualClock):
    """ManualClock that advances 1 ms per read so created_at ordering is deterministic."""

    def now(self):
        t = super().now()
        self.advance(0.001)
        return t


@pytest.fixture
def events():
    return Events()


@pytest.fixture
def service(tmp_path, events):
    clock = Ticking(datetime(2026, 10, 16, 3, 4, 5, tzinfo=UTC))
    db = Database(tmp_path / "gs.db", clock)
    db.migrate()
    return CalibrationService(Repo(db), events, clock)


def test_default_maps_centred_square_corners_to_raster_corners():
    H = default_homography(800, 600)
    for src, dst in [((100, 0), (0, 0)), ((700, 0), (512, 0)), ((700, 600), (512, 512)), ((100, 600), (0, 512))]:
        assert np.allclose(apply_h(H, src), dst, atol=1e-6)


def test_click_order_and_north_edge_normalise():
    shuffled = [SQ[2], SQ[0], SQ[3], SQ[1]]
    assert normalise_corners(shuffled, north_edge=0) == normalise_corners(SQ, north_edge=0)
    assert normalise_corners(SQ, north_edge=1)[0] == SQ[1]
    assert normalise_corners(SQ, north_edge=0)[0] == SQ[0]


def test_non_convex_corners_rejected():
    with pytest.raises(CalibrationError, match="non_convex"):
        normalise_corners([(0, 0), (100, 0), (20, 20), (0, 100)], north_edge=0)


def test_degenerate_uses_frame_fraction_when_given():
    tiny = [(0, 0), (10, 0), (10, 10), (0, 10)]  # 100 px^2: fine alone, < 1% of 800x600
    assert len(normalise_corners(tiny, 0)) == 4
    with pytest.raises(CalibrationError, match="degenerate"):
        normalise_corners(tiny, 0, frame_wh=(800, 600))
    with pytest.raises(CalibrationError, match="degenerate"):
        normalise_corners([(0, 0), (1, 0), (1, 0.5), (0, 0.5)], 0)


def test_rectify_generated_quadrants_land_north_up():
    img = np.zeros((600, 800, 3), np.uint8)
    img[:300, :400] = (0, 0, 255)
    out = CalibrationService.rectify_with(default_homography(800, 600), img)
    assert out.shape == (512, 512, 3) and tuple(out[10, 10]) == (0, 0, 255)


def test_rectify_scales_homography_when_frame_size_changes(service):
    img = np.zeros((1200, 1600, 3), np.uint8)  # 2x the calibrated 800x600
    img[:600, :800] = (0, 0, 255)
    out = service.rectify(img)
    assert tuple(out[10, 10]) == (0, 0, 255) and tuple(out[500, 500]) == (0, 0, 0)


def test_four_corner_north_edge_rotates_raster(service):
    img = np.zeros((600, 800, 3), np.uint8)
    cv2.fillPoly(img, [np.array(SQ, np.int32)], (255, 255, 255))
    cal = service.set_four_corner(SQ, 0, 800, 600)
    assert tuple(service.rectify(img)[256, 256]) == (255, 255, 255)
    assert np.allclose(apply_h(np.array(cal.homography).reshape(3, 3), SQ[0]), (0, 0), atol=1e-4)
    cal = service.set_four_corner(SQ, 1, 800, 600)
    assert np.allclose(apply_h(np.array(cal.homography).reshape(3, 3), SQ[1]), (0, 0), atol=1e-4)


def test_only_one_active_calibration(service, events):
    service.set_four_corner(SQ, north_edge=0, frame_w=800, frame_h=600)
    service.reset(800, 600)
    rows = service.repo.query("select mode, active from calibrations order by created_at", ())
    assert [r["active"] for r in rows] == [False, False, True] and rows[-1]["mode"] == "default"
    assert [r["mode"] for r in rows] == ["default", "four_corner", "default"]
    assert events.count("calibration.updated") == 2
    assert service.active().active is True


def test_swap_is_atomic_when_insert_fails(service):
    before = service.active()
    bad = {**service._new_row("default", 800, 600, None, None, np.eye(3)), "bogus": 1}
    with pytest.raises(ValueError):
        service._swap(bad)
    assert service.active() == before
    assert len(service.repo.query("select id from calibrations", ())) == 1
    outbox = service.repo.query("select count(*) as n from sync_outbox", ())
    assert outbox[0]["n"] == 1
