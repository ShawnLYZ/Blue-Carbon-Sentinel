import asyncio
from datetime import UTC, datetime

import cv2
import numpy as np
from bcs_gs.api.models import Calibration
from bcs_gs.camera.imagery import CameraImagerySource, to_site_raster
from bcs_gs.camera.link import Frame
from bcs_gs.site.calibration import default_homography

T0 = datetime(2026, 10, 8, 3, 0, 0, tzinfo=UTC)
CAL_DEFAULT = Calibration(
    id="cal-default", created_at="2026-10-08T03:00:00.000Z", mode="default", frame_w=800, frame_h=600,
    homography=[float(v) for v in default_homography(800, 600).reshape(9)], active=True,
)  # fmt: skip


def resize(im):
    return cv2.resize(im, (512, 512))


def test_to_site_raster_is_rgb_north_up_with_metadata():
    frame = Frame(image_bgr=np.full((600, 800, 3), (255, 0, 0), np.uint8), seq=7, captured_at=T0)  # pure blue in BGR
    r = to_site_raster(frame, CAL_DEFAULT, rectify=resize)
    assert r.image.shape == (512, 512, 3) and tuple(r.image[0, 0]) == (0, 0, 255)  # RGB blue
    assert (r.bands, r.source_id, r.seq, r.calibration_id) == (("R", "G", "B"), "esp32cam", 7, CAL_DEFAULT.id)
    assert r.captured_at == T0 and r.image.dtype == np.uint8 and r.image.flags.c_contiguous


def test_raster_is_a_copy_not_a_view_of_the_frame():
    img = np.zeros((512, 512, 3), np.uint8)
    r = to_site_raster(Frame(img, 1, T0), CAL_DEFAULT, rectify=lambda im: im)
    img[:] = 9
    assert int(r.image.max()) == 0 and not np.shares_memory(r.image, img)


class StubStatus:
    online = True


class StubCamera:
    def __init__(self, frames):
        self.frames = frames

    def status(self):
        return StubStatus()

    def latest(self):
        return self.frames[-1] if self.frames else None

    def recent(self, n):
        return self.frames[-n:]

    async def subscribe(self):
        for f in self.frames:
            yield f


class StubCal:
    def active(self):
        return CAL_DEFAULT

    def rectify(self, im):
        return resize(im)


def _frames():
    return [Frame(np.full((600, 800, 3), (i * 10, 0, 0), np.uint8), i, T0) for i in range(1, 5)]


def test_camera_imagery_source_latest_recent_online():
    src = CameraImagerySource(StubCamera(_frames()), StubCal())
    assert src.source_id == "esp32cam" and src.online()
    assert src.latest().seq == 4
    assert [r.seq for r in src.recent(2)] == [3, 4]
    assert tuple(src.recent(1)[0].image[0, 0]) == (0, 0, 40)
    assert CameraImagerySource(StubCamera([]), StubCal()).latest() is None


def test_camera_imagery_source_subscribe_maps_frames():
    async def run():
        return [r async for r in CameraImagerySource(StubCamera(_frames()), StubCal()).subscribe()]

    out = asyncio.run(run())
    assert [r.seq for r in out] == [1, 2, 3, 4] and all(r.calibration_id == "cal-default" for r in out)
