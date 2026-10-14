"""Seam-1 assessment helpers and fixtures (M4 Task 5), built on ``world`` / ``world_with_sim``.

- ``await seed_healthy_baseline(world)``: an evidence-grade seeded capture with healthy default metrics
  for every zone (it becomes the baseline, so the vegetation stressor is measured and ~0).
- ``await seed_flag(world, zone_id)``: a real flag through the M2 pipeline. It seeds a healthy baseline
  first when there is none, then a capture with 15 pp canopy loss in the zone, so the capture service
  emits ``zone.metrics`` and ``zone.flagged`` and the vegetation stressor is measured. (``gs_tasking.seed_flag``
  publishes a bare ``zone.flagged`` on the bus instead and stays as it is for the tasking tests.)
- ``world_offline_ai``: ``world`` whose Gemini and Ollama providers raise ``unavailable`` on every call,
  as with the network off, so every role answers from the rules tier.
- ``world.sim`` (on ``world_with_sim``): ``apply(zone_label, scenario, ramp_s=None)`` and
  ``set_value(node_id, parameter, value, behaviour="hold")`` on the running simulator, as the
  simulator's control API does.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from bcs_gs.ai.providers.fake import FakeProvider

HEALTHY_CANOPY_PCT = 60.0
FLAG_CANOPY_PCT = 45.0  # 15 pp loss against the healthy baseline: over the 10 pp canopy_loss threshold


async def _seed_capture(world: Any, zone_metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    r = await world.http.post(
        "/api/v1/test/seed/capture", json={"zone_metrics": zone_metrics, "evidence_grade": True}
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


async def seed_healthy_baseline(world: Any) -> dict[str, Any]:
    cap = await _seed_capture(world, {})
    assert cap["is_baseline"], "a healthy baseline was expected"
    return cap


async def seed_flag(world: Any, zone_id: str) -> dict[str, Any]:
    caps = (await world.http.get("/api/v1/captures")).json()
    if not any(c["is_baseline"] for c in caps):
        await seed_healthy_baseline(world)
    cap = await _seed_capture(world, {zone_id: {"canopy_pct": FLAG_CANOPY_PCT}})
    assert cap["flagged"], cap
    return cap


@pytest.fixture
async def world_offline_ai(world: Any) -> AsyncIterator[Any]:
    gateway = world.gs.services.ai
    # An empty FakeProvider script raises ProviderError("unavailable") on every call.
    gateway.providers.update(
        {"gemini": FakeProvider(provider="gemini"), "ollama": FakeProvider(provider="ollama")}
    )
    yield world


class SimControl:
    """Scenario and slider control of a running simulator ``Runtime`` (under its lock)."""

    def __init__(self, rt: Any) -> None:
        self.rt = rt

    def apply(self, zone_label: str, scenario: str, ramp_s: float | None = None) -> None:
        with self.rt.lock:
            self.rt.scenarios.apply(zone_label, scenario, ramp_s)

    def set_value(self, node_id: str, parameter: str, value: float, behaviour: str = "hold") -> None:
        with self.rt.lock:
            self.rt.overrides.set(node_id, parameter, value, behaviour)

    def fault(self, node_id: str, kind: str, **params: Any) -> None:
        """Inject a simulator fault (``offline``, ``low_battery``, ...); it acts at the next ``run_for``."""
        with self.rt.lock:
            self.rt.faults(node_id).inject(kind, params or None)


def _generated_class_map() -> Any:
    """A generated 512 x 512 class-code array with canopy blobs (code 1) on water (code 2). Not an image
    of anything: it only stands in for classes.png so tree location has input."""
    import numpy as np

    classes = np.full((512, 512), 2, np.uint8)
    for cy, cx in ((60, 80), (120, 400), (260, 250), (330, 90), (400, 420), (470, 200)):
        classes[cy - 12 : cy + 12, cx - 12 : cx + 12] = 1
    return classes


async def set_seeded_baseline(world: Any, with_classes: bool = False) -> dict[str, Any]:
    """Seed the healthy baseline capture; ``with_classes`` also stores a generated class map for it."""
    cap = await seed_healthy_baseline(world)
    if with_classes:
        import asyncio
        import time

        from bcs_gs.capture.artefacts import BUCKET, CONTENT_TYPES, indexed_png, media_keys
        from bcs_protocol.timefmt import from_iso

        svc = world.gs.services
        key = media_keys(cap["id"], from_iso(cap["taken_at"]))["classes"]
        data = indexed_png(_generated_class_map())

        def store() -> None:
            # The baseline's synthetic class map (ruling R22a) may be read by tree location right now:
            # on Windows replacing an open file fails, so retry briefly.
            for attempt in range(50):
                try:
                    svc.media.put(BUCKET, key, data, CONTENT_TYPES["classes"], protected=True, cloud=False)
                    break
                except PermissionError:
                    if attempt == 49:
                        raise
                    time.sleep(0.05)
            row = svc.repo.get("captures", {"id": cap["id"]})
            svc.repo.upsert("captures", {**row, "media": {**(row["media"] or {}), "classes": key}}, sync=False)

        await asyncio.to_thread(store)
    return cap
