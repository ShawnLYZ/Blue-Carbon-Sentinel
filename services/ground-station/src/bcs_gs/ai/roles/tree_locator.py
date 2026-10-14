"""TreeLocator: tree points on the site raster (vision tier first, blob centroids as rules)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, Field

from bcs_gs.ai.providers.base import ProviderRequest
from bcs_gs.ai.roles._common import (
    RoleConfig,
    default_role_config,
    downscale_jpeg,
    load_prompt,
    response_schema,
)
from bcs_gs.ai.roles.base import OutputRejected
from bcs_gs.vegetation.trees import blob_centroids

MAX_POINTS = 400


class TreePoint(BaseModel):
    y: float = Field(ge=0, le=1000)  # normalised 0-1000, as the vision models point
    x: float = Field(ge=0, le=1000)
    label: str = "tree"


class TreeOutput(BaseModel):
    points: list[TreePoint] = Field(max_length=MAX_POINTS)


@dataclass
class TreeInput:
    raster_jpeg: bytes
    classes: np.ndarray | None = None  # class codes (canopy = 1); used by the rules tier only


class TreeLocator:
    name = "tree_locator"
    schema_version = "1"
    prompt_version = "v1"
    output_model = TreeOutput

    def __init__(self, cfg: RoleConfig | None = None) -> None:
        self.cfg = cfg or default_role_config()

    def request(self, inp: TreeInput) -> ProviderRequest:
        return ProviderRequest(
            role=self.name,
            system=load_prompt(self.name, self.prompt_version),
            parts=[
                "Point at each tree crown in the image.",
                downscale_jpeg(inp.raster_jpeg, self.cfg.max_image_px),
            ],
            response_schema=response_schema(TreeOutput),
            temperature=self.cfg.temperature,
            timeout_s=self.cfg.vision_timeout_s,
        )

    def check(self, out: TreeOutput, inp: TreeInput) -> TreeOutput:
        if len(out.points) > MAX_POINTS:
            raise OutputRejected(f"{len(out.points)} points exceed {MAX_POINTS}")
        for p in out.points:
            if not (0 <= p.y <= 1000 and 0 <= p.x <= 1000):
                raise OutputRejected("point outside 0-1000")
        return out

    def rules(self, inp: TreeInput) -> TreeOutput:
        if inp.classes is None:
            return TreeOutput(points=[])
        h, w = inp.classes.shape[:2]
        cents = blob_centroids(inp.classes, min_area_px=30)[:MAX_POINTS]
        return TreeOutput(points=[TreePoint(y=y / h * 1000, x=x / w * 1000, label="tree") for y, x in cents])
