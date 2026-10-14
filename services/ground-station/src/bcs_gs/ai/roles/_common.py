"""Shared helpers for the AI roles: prompt loading, schema simplification, image downscaling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel

from bcs_gs.ai.roles.base import OutputRejected
from bcs_gs.core.config import Settings, load_settings
from bcs_gs.fusion.bands import BAND_KEY

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

@dataclass(frozen=True)
class RoleConfig:
    """Values the roles take from configuration (ai.yaml, risk.yaml, bands.yaml)."""

    temperature: float
    text_timeout_s: float
    vision_timeout_s: float
    max_image_px: int
    weights: dict[str, float]
    units: dict[str, str]
    multiplier_bounds: tuple[float, float]

    @classmethod
    def from_settings(cls, s: Settings) -> RoleConfig:
        units = {
            stressor: u
            for stressor, key in BAND_KEY.items()
            if (u := getattr(s.bands.parameters.get(key), "unit", None))
        }
        return cls(
            temperature=s.ai.temperature,
            text_timeout_s=float(s.ai.timeouts_s["text"]),
            vision_timeout_s=float(s.ai.timeouts_s["vision"]),
            max_image_px=int(s.ai.image["max_px"]),
            weights=dict(s.risk.weights),
            units=units,
            multiplier_bounds=(float(s.risk.multiplier_bounds[0]), float(s.risk.multiplier_bounds[1])),
        )


def _repo_root() -> Path:
    for p in Path(__file__).resolve().parents:
        if (p / "config" / "ai.yaml").exists():
            return p
    raise FileNotFoundError("config/ai.yaml not found above the roles package")


@lru_cache(maxsize=1)
def default_role_config() -> RoleConfig:
    """The committed configuration, read once (no .env, no overrides)."""
    return RoleConfig.from_settings(load_settings(_repo_root(), env_file=None))


NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*%|(\d+\.\d+)")  # a percentage or a decimal; bare integers pass


def numeric_values(obj: Any) -> list[float]:
    """Absolute values of every number in a (nested) dict / list / Pydantic model; flags included."""
    if isinstance(obj, BaseModel):
        return numeric_values(obj.model_dump())
    if isinstance(obj, bool):
        return []
    if isinstance(obj, int | float):
        return [abs(float(obj))]
    if isinstance(obj, dict):
        return [v for x in obj.values() for v in numeric_values(x)]
    if isinstance(obj, list | tuple):
        return [v for x in obj for v in numeric_values(x)]
    return []


def reject_foreign_numbers(texts: list[str], allowed: list[float]) -> None:
    """Raise OutputRejected when a text states a percentage or decimal that is not in ``allowed``,
    compared at the precision written (38 equals 38.0; 37.96 may be written 38.0)."""
    for text in texts:
        for mt in NUMBER.finditer(text):
            token = mt.group(1) or mt.group(2)
            decimals = len(token.split(".")[1]) if "." in token else 0
            n = round(float(token), decimals)
            if not any(round(a, decimals) == n for a in allowed):
                raise OutputRejected(f"number {token} in AI text is not in the measured inputs")


def load_prompt(name: str, version: str) -> str:
    return (PROMPTS / f"{name}.{version}.md").read_text(encoding="utf-8")


def response_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON Schema with ``$ref`` inlined and titles dropped (provider-friendly)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def downscale_jpeg(data: bytes, max_side: int) -> bytes:
    """Re-encode a JPEG so its long side is <= ``max_side``; unchanged when already small or undecodable."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return data
    h, w = img.shape[:2]
    if max(h, w) <= max_side:
        return data
    s = max_side / max(h, w)
    img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buf.tobytes() if ok else data


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
