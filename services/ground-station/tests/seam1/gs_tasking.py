"""Seam-1 tasking fixtures and helpers (Tasks 10-11), built on ``world`` (gs_world.py).

- ``world_with_sim``: ``world`` plus a running simulator ``Runtime`` acting as the 8 nodes on the Ground
  Station's ManualClock, so commands get real acks (``world.runtime``; ``world.sim`` controls scenarios).
- ``world_no_ack``: ``world`` whose 8 test nodes receive commands but hold every ack until
  ``world.release_acks()``; ``world.last_cmd_mode_for_each_node()`` is the last ``set_mode`` mode each
  node received (one value when all agree, else ``{node: mode}``); ``world.received[node]`` lists them.
- ``await trigger(world, zone, kind="zone_flag")``: calls the controller on the Ground Station loop and
  returns the I3 Task dict, or None (cooldown / no coverage).
- ``await manual_task(world, zone)``: a manual task through POST /tasks (returns the Task dict).
- ``await seed_flag(world, zone_id)``: publishes a ``zone.flagged`` event on the GS EventBus as M2 does.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator, Coroutine
from typing import Any

import pytest
from bcs_gs.api.events import ZoneFlaggedEvent
from bcs_gs.core.ids import uuid7
from gs_assess import SimControl


def _loop(world: Any) -> asyncio.AbstractEventLoop:
    loop = world.gs.services.tasking.loop
    assert loop is not None, "tasking controller not started"
    return loop


async def on_gs(world: Any, coro: Coroutine[Any, Any, Any]) -> Any:
    """Run ``coro`` on the Ground Station's event loop and await its result."""
    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, _loop(world)))


async def trigger(
    world: Any, zone_id: str, kind: str = "zone_flag", reason: str | None = None
) -> dict | None:
    tasking = world.gs.services.tasking
    task = await on_gs(world, tasking.trigger(zone_id, kind, reason or f"test {kind} for {zone_id}"))
    return None if task is None else task.model_dump(mode="json")


async def seed_flag(world: Any, zone_id: str, kinds: tuple[str, ...] = ("canopy_loss",)) -> None:
    data = ZoneFlaggedEvent.model_validate({
        "capture_id": uuid7(), "zone_id": zone_id,
        "flags": [{"kind": k, "value": 12.0, "threshold": 5.0} for k in kinds],
    }).model_dump(mode="json")  # fmt: skip
    bus = world.gs.services.bus
    _loop(world).call_soon_threadsafe(bus.publish, "zone.flagged", data)


async def manual_task(world: Any, zone_id: str, reason: str | None = None) -> dict:
    """The operator's manual task for a zone through the API (POST /tasks); returns the I3 Task dict."""
    r = await world.http.post("/api/v1/tasks", json={"zone_id": zone_id, "reason": reason or f"manual {zone_id}"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
async def world_with_sim(world: Any, sim_runtime_factory: Any) -> AsyncIterator[Any]:
    rt = sim_runtime_factory(clock=world.clock)  # the nodes share the Ground Station's ManualClock
    await asyncio.to_thread(rt.start)
    rt.run_background()
    for node_id in world.keys:
        await world.wait_status(node_id, "online", timeout=20)
    for _ in range(200):  # every node has delivered its first sample
        if len(await asyncio.to_thread(world.ingest.latest_all)) >= len(world.keys):
            break
        await asyncio.sleep(0.1)
    world.runtime = rt
    world.sim = SimControl(rt)  # scenario / slider control (M4 Task 5)

    def run_for(seconds: float, step_s: float = 10.0) -> None:
        """Advance the shared ManualClock in steps, stepping the simulator at each so due samples are made."""
        done = 0.0
        while done < seconds:
            dt = min(step_s, seconds - done)
            world.clock.advance(dt)
            rt.step(world.clock.now())
            if world.gs.cloud.failing:  # the background worker keeps trying (and failing) through an outage
                asyncio.run_coroutine_threadsafe(world.gs.services.sync.drain_once(), _loop(world)).result(30)
            done += dt

    world.run_for = run_for
    yield world


class _NoAck:
    """The 8 test nodes, subscribed to their own ``cmd`` topics, holding every ack."""

    def __init__(self, world: Any) -> None:
        self.world = world
        self.received: dict[str, list[dict[str, Any]]] = {n: [] for n in world.keys}
        self.held: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        for node_id in world.keys:
            node = world.node(node_id)
            subscribed = threading.Event()
            node.client.on_message = lambda _c, _u, msg, n=node_id: self._on_cmd(n, msg.payload)
            node.client.on_subscribe = lambda *_a, ev=subscribed: ev.set()
            node.client.subscribe(node.topic("cmd"), qos=1)
            if not subscribed.wait(5):
                raise RuntimeError(f"{node_id} could not subscribe to its commands")

    def _on_cmd(self, node_id: str, payload: bytes) -> None:
        cmd = json.loads(payload)
        with self._lock:
            self.received[node_id].append(cmd)
            if (node_id, cmd["command_id"]) not in self.held:
                self.held.append((node_id, cmd["command_id"]))

    def wait_delivered(self, timeout: float = 5) -> None:
        """Until every command the Ground Station stored has reached its node."""
        repo = self.world.gs.repo
        deadline = time.monotonic() + timeout
        while True:
            sent = {(r["node_id"], r["id"]) for r in repo.query("SELECT node_id, id FROM commands")}
            with self._lock:
                got = {(n, c["command_id"]) for n, cs in self.received.items() for c in cs}
            if sent <= got:
                return
            if time.monotonic() > deadline:
                raise AssertionError(f"commands not delivered: {sorted(sent - got)}")
            time.sleep(0.01)

    def release_acks(self) -> None:
        self.wait_delivered()
        with self._lock:
            held, self.held = self.held, []
        for node_id, command_id in held:
            self.world.node(node_id).publish_ack(command_id, "accepted")

    def last_cmd_mode_for_each_node(self) -> str | dict[str, str]:
        self.wait_delivered()
        with self._lock:
            modes = {n: cs[-1]["params"]["mode"] for n, cs in self.received.items() if cs}
        values = set(modes.values())
        return values.pop() if len(values) == 1 else modes


@pytest.fixture
async def world_no_ack(world: Any) -> AsyncIterator[Any]:
    na = await asyncio.to_thread(_NoAck, world)
    world.received = na.received
    world.release_acks = na.release_acks
    world.last_cmd_mode_for_each_node = na.last_cmd_mode_for_each_node
    yield world
