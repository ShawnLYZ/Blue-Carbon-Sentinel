"""Live NVIDIA FLUX.2 Klein check (addendum R): one 1024 x 1024 edit with the real ``BCS_NVIDIA_API_KEY``
from ``.env``. Marker ``live``; never in CI, never in a default run. Run by hand, once:
``uv run pytest services/ground-station/tests/live/test_live_flux.py -m live -q``. The outcome is
recorded in ``bcs_gs.futures.illustrator`` (module docstring, LIVE_CHECK_RESULT). On 2026-10-13 it
failed with ``bad_response: NVIDIA returned 422 (Expected: example_id, got: base64)``: the hosted
endpoint edits only NVIDIA's example images with this key."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from bcs_gs.core.config import load_settings
from bcs_gs.futures.illustrator import IllustratorError, NvidiaFluxIllustrator
from bcs_gs.futures.instruction import SUFFIX

ROOT = Path(__file__).resolve().parents[4]


def _generated_site_jpeg() -> bytes:
    """A generated 1024 x 1024 scene: water on the left, green canopy blobs on mud on the right."""
    img = np.zeros((1024, 1024, 3), np.uint8)
    img[:, :] = (60, 101, 139)  # mud (BGR)
    img[:, :300] = (200, 100, 30)  # water
    rng = np.random.default_rng(42)
    for _ in range(60):
        x, y = int(rng.integers(350, 1000)), int(rng.integers(20, 1000))
        cv2.circle(img, (x, y), int(rng.integers(20, 50)), (40, 140, 40), -1)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


@pytest.mark.live
async def test_live_flux_one_1024_edit_within_15_s():
    s = load_settings(ROOT, env_file=ROOT / ".env")
    key = s.nvidia_api_key
    if key is None or not key.get_secret_value():
        pytest.skip("no BCS_NVIDIA_API_KEY in .env")
    flux = NvidiaFluxIllustrator(key.get_secret_value(), model=s.ai.models["image"])
    instruction = (
        "By 2035 without intervention, in the north-east zone about 40% of the mangrove canopy turns "
        f"brown-grey with dieback. {SUFFIX}"
    )
    t0 = time.monotonic()
    try:
        out = await flux.edit(_generated_site_jpeg(), instruction, (1024, 1024), 42, 4)
    except IllustratorError as e:
        pytest.fail(f"FLUX edit failed: {e} after {time.monotonic() - t0:.1f} s")
    elapsed = time.monotonic() - t0
    img = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    print(f"FLUX edit: {img.shape}, {len(out)} bytes, {elapsed:.1f} s")
    assert img.shape[:2] == (1024, 1024)
    assert elapsed <= 15
