"""Depth Anything V2 Small contract on the real weights (marker ``model``; skipped when absent)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pytest
from bcs_gs.models_paths import DEPTH_MODEL_FILES, depth_model_dir
from bcs_gs.reality import DepthRunner

REPO_ROOT = Path(__file__).resolve().parents[4]
MODEL_DIR = depth_model_dir(REPO_ROOT)

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(
        not any((MODEL_DIR / f).is_file() for f in DEPTH_MODEL_FILES),
        reason="depth model weights absent (run the model fetcher)",
    ),
]


@pytest.mark.model
def test_depth_model_contract_on_random_input(caplog):
    caplog.set_level(logging.INFO, logger="bcs_gs.reality")
    r = DepthRunner(MODEL_DIR)
    assert r.available and r.provider is not None
    out = r.infer(np.random.default_rng(0).integers(0, 255, (512, 512, 3), np.uint8))
    assert out.shape == (518, 518) and out.dtype == np.float32 and np.isfinite(out).all()
    assert any(r.provider in rec.getMessage() for rec in caplog.records)
    t = time.perf_counter()
    for _ in range(5):
        r.infer(np.random.default_rng(1).integers(0, 255, (512, 512, 3), np.uint8))
    print(
        f"\ndepth provider={r.provider} model={r.model_file} ms/frame={(time.perf_counter() - t) * 200:.1f}"
    )
