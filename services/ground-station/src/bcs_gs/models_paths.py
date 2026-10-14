"""On-disk layout of downloaded models (shared by preflight and the model fetcher)."""

from __future__ import annotations

from pathlib import Path

DEPTH_MODEL_DIR_NAME = "depth-anything-v2-small"
# fp16 is preferred; the fp32 model is the fallback. Either one makes the depth model present.
DEPTH_MODEL_FILES = ("model_fp16.onnx", "model.onnx")


def depth_model_dir(root: Path) -> Path:
    return root / "var" / "models" / DEPTH_MODEL_DIR_NAME
