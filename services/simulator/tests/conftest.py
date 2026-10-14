"""Fixtures for the headless runner: a real ``Runtime`` over the in-memory transport and a stub Ground Station."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from bcs_sim.client import MemoryHub
from bcs_sim.clock import ManualClock
from bcs_sim.config import load_sim_config
from bcs_sim.gs_client import SimNodeSpec
from bcs_sim.runtime import Runtime

RUN_T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)
NODES_8 = [
    ("WQ-01", "water_quality", 50.0, 50.0, "A1"),
    ("WQ-02", "water_quality", 160.0, 250.0, "B3"),
    ("WQ-03", "water_quality", 350.0, 150.0, "D2"),
    ("WQ-04", "water_quality", 250.0, 400.0, "C5"),
    ("SP-01", "soil_probe", 150.0, 150.0, "B2"),
    ("SP-02", "soil_probe", 140.0, 260.0, "B3"),
    ("SP-03", "soil_probe", 150.0, 370.0, "B4"),
    ("TG-01", "tide_gauge", 250.0, 250.0, "C3"),
]


class RunnerStubGs:
    """A GsClient stand-in: fixed registry, throw-away credentials, remembers uploads."""

    def __init__(self) -> None:
        self.specs = [SimNodeSpec(n, t, e, s, z, "KSL") for n, t, e, s, z in NODES_8]
        self.uploads: list[tuple[dict[str, Any], Path]] = []

    def registry(self) -> list[SimNodeSpec]:
        return list(self.specs)

    def credentials(self, node_ids: list[str] | None = None) -> dict[str, str]:
        ids = node_ids if node_ids is not None else [s.node_id for s in self.specs]
        return {n: f"pw-{n}" for n in ids}

    def upload_session(self, meta: dict[str, Any], path: Path) -> dict[str, Any]:
        self.uploads.append((meta, path))
        return {"id": meta["id"]}


@pytest.fixture
def fake_runtime_factory(tmp_path: Path) -> Iterator[Callable[..., Runtime]]:
    """``fake_runtime_factory(seed=...)``: a started Runtime on a MemoryHub (no broker). Its clock is
    a ``ManualClock`` at ``RUN_T0``; ``rt.hub`` and ``rt.fake_gs`` expose the transport and the stub GS."""
    made: list[Runtime] = []

    def make(seed: int = 0, clock: ManualClock | None = None, demo_time_scale: bool = True) -> Runtime:
        hub, gs = MemoryHub(), RunnerStubGs()
        clock = clock or ManualClock(RUN_T0)
        sessions = tmp_path / f"sessions-{len(made)}"
        rt = Runtime(
            load_sim_config(),
            gs,
            clock,
            seed,
            client_factory=hub.factory,
            sessions_dir=sessions,
            demo_time_scale=demo_time_scale,
        )
        rt.start()
        rt.hub, rt.fake_gs = hub, gs  # type: ignore[attr-defined]
        made.append(rt)
        return rt

    yield make
    for rt in made:
        rt.stop()
