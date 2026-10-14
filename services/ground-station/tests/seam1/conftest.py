"""Seam-1 fixtures for the Ground Station. ``gs_broker`` (the Ground Station against a real Mosquitto
with an empty node registry) is defined in ``tests/conftest.py``; ``sim_runtime_factory`` lives here and
``world`` (ingest running, the 8 standard nodes registered, test node publishers) in ``gs_world.py``."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gs_assess import world_offline_ai  # noqa: F401  (M4 Task 5)
from gs_eligibility import (  # noqa: F401  (M6 Task 4)
    world_projected,
    world_projected_rules_only_unlocked,
    world_projected_uncovered_zone,
)
from gs_forecast import world_ready  # noqa: F401  (M5 Task 3)
from gs_hydration import cloud_with_history  # noqa: F401  (M7 Task 3)
from gs_ledger import world_applied_plan, world_plan_not_applied  # noqa: F401  (M6 Task 3)
from gs_seam1_helpers import STANDARD_8
from gs_tasking import world_no_ack, world_with_sim  # noqa: F401  (Task 10-11 tasking worlds)
from gs_world import world  # noqa: F401  (the Task 9-11 world fixture)


@pytest.fixture
def sim_runtime_factory(gs_broker: Any) -> Iterator[Callable[..., Any]]:
    """Build a real simulator ``Runtime`` against the gs_broker's URL, sim token and broker port
    (``clock=`` overrides its own ManualClock, e.g. with the Ground Station's).

    An empty registry first gets the standard 8 simulated nodes (WQ-01..04, SP-01..03, TG-01). Call it
    again for a restarted simulator. Runtimes still started are stopped at teardown."""
    from bcs_sim.clock import ManualClock
    from bcs_sim.config import load_sim_config
    from bcs_sim.gs_client import GsClient
    from bcs_sim.runtime import Runtime

    made: list[Runtime] = []
    clients: list[GsClient] = []

    def factory(**kw: Any) -> Runtime:
        reg = gs_broker.registry
        if not reg.nodes():
            for node_type, e_m, s_m in STANDARD_8:
                reg.install(node_type, "simulated", e_m, s_m)
        token = gs_broker.settings.sim_shared_token.get_secret_value()
        client = GsClient(gs_broker.url, token)
        clients.append(client)
        kw.setdefault("watch_registry", False)
        clock = kw.pop("clock", None) or ManualClock(gs_broker.clock.now())
        rt = Runtime(
            load_sim_config(), client, clock, seed=42,
            broker_host=gs_broker.mqtt.host, broker_port=gs_broker.mqtt.port, **kw,
        )  # fmt: skip
        made.append(rt)
        return rt

    yield factory
    for rt in made:
        if rt.started:
            rt.stop()
    for c in clients:
        c.close()
