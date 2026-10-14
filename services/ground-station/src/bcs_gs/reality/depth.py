"""Depth Anything V2 Small on ONNX Runtime, DirectML first (addendum N10, R).

``DepthRunner`` never raises from construction: with no weights, or when every model file fails
to load, it is ``available = False`` and the RealityLayer uses the colour-class fallback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from bcs_gs.models_paths import DEPTH_MODEL_FILES

log = logging.getLogger("bcs_gs.reality")

INPUT_SIZE = 518  # multiple of the ViT patch size 14
_MEAN = np.array((0.485, 0.456, 0.406), np.float32)
_STD = np.array((0.229, 0.224, 0.225), np.float32)
_ORT_DTYPES = {"tensor(float)": np.float32, "tensor(float16)": np.float16}


def preprocess(rgb512: np.ndarray) -> np.ndarray:
    """RGB uint8 H x W x 3 -> 1 x 3 x 518 x 518 float32, ImageNet mean/std normalised."""
    img = cv2.resize(np.ascontiguousarray(rgb512), (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_CUBIC)
    x = (img.astype(np.float32) / np.float32(255.0) - _MEAN) / _STD
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None], dtype=np.float32)


class DepthRunner:
    def __init__(
        self,
        model_dir: Path,
        prefer: tuple[str, ...] = ("DmlExecutionProvider", "CPUExecutionProvider"),
        *,
        load: bool = True,
    ) -> None:
        """``load=False`` builds an unavailable runner without touching the weights (test mode)."""
        self.available = False
        self.provider: str | None = None
        self.model_file: str | None = None
        self._session: Any = None
        self._in_name = self._out_name = ""
        self._in_dtype: Any = np.float32
        if not load:
            return
        try:
            import onnxruntime as ort
        except Exception as exc:  # noqa: BLE001
            log.warning("depth model unavailable: onnxruntime import failed (%s)", type(exc).__name__)
            return
        have = set(ort.get_available_providers())
        providers = [p for p in prefer if p in have] or ["CPUExecutionProvider"]
        for name in DEPTH_MODEL_FILES:  # fp16 first, fp32 on a load error
            path = Path(model_dir) / name
            if not path.is_file():
                continue
            try:
                opts = ort.SessionOptions()
                opts.log_severity_level = 3
                session = ort.InferenceSession(str(path), sess_options=opts, providers=providers)
            except Exception as exc:  # noqa: BLE001
                log.warning("depth model %s failed to load: %s", name, type(exc).__name__)
                continue
            inp, out = session.get_inputs()[0], session.get_outputs()[0]
            self._session, self._in_name, self._out_name = session, inp.name, out.name
            self._in_dtype = _ORT_DTYPES.get(inp.type, np.float32)
            self.provider = session.get_providers()[0]
            self.model_file = name
            self.available = True
            log.info(
                "depth model %s loaded on %s (input %s %s, output %s)",
                name, self.provider, inp.name, inp.shape, out.name,
            )  # fmt: skip
            return
        log.warning("depth model unavailable: no loadable model in %s", model_dir)

    def infer(self, rgb512: np.ndarray) -> np.ndarray:
        """Relative inverse depth, float32 518 x 518 (larger = nearer)."""
        if not self.available:
            raise RuntimeError("depth model is not available")
        x = preprocess(rgb512).astype(self._in_dtype, copy=False)
        y = np.asarray(self._session.run([self._out_name], {self._in_name: x})[0])
        d = np.squeeze(y).astype(np.float32, copy=False)
        if d.shape != (INPUT_SIZE, INPUT_SIZE):
            d = cv2.resize(d, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)
        return d
