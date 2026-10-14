"""Seam 2: tasking policy (§15, N9, F5, G5, N12) against an in-memory MQTT stand-in and a real local store."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from bcs_gs.core.clock import ManualClock
from bcs_gs.core.config import load_settings
from bcs_gs.core.events import EventBus
from bcs_gs.nodes.coverage import by_zone, coverage
from bcs_gs.site.registry import SiteRegistry
from bcs_gs.store.db import Database
from bcs_gs.store.repo import Repo
from bcs_gs.tasking.controller import TaskingController, select_nodes
from bcs_protocol.timefmt import from_iso, to_iso
from bcs_protocol.validate import parse_message

REPO_ROOT = Path(__file__).resolve().parents[4]
T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)


@dataclass(frozen=True)
class N:
    id: str
    node_type: str
    e_m: float
    s_m: float
    status: str = "online"
    kind: str = "sentinel_node"

    @property
    def zone_id(self) -> str:
        return f"KSL-{'ABCDE'[int(self.e_m // 100)]}{int(self.s_m // 100) + 1}"


# KSL-B3's centre is (150, 250) m. Covering it: WQ-02 10 m, SP-01 30 m, WQ-01 100 m, WQ-03 140 m.
NODES = [
    N("WQ-01", "water_quality", 150.0, 150.0),
    N("WQ-02", "water_quality", 160.0, 250.0),
    N("WQ-03", "water_quality", 150.0, 390.0),
    N("WQ-04", "water_quality", 450.0, 50.0),
    N("SP-01", "soil_probe", 150.0, 280.0),
    N("SP-02", "soil_probe", 450.0, 450.0),
    N("TG-01", "tide_gauge", 0.0, 250.0),
]
COVERAGE = coverage(NODES)


# ---- select_nodes ---------------------------------------------------------------------------------
def test_select_nodes_nearest_first_max_four_plus_tide_gauge():
    assert select_nodes("KSL-B3", NODES, COVERAGE) == ["WQ-02", "SP-01", "WQ-01", "TG-01"]


def test_select_nodes_accepts_by_zone_map_and_without_tide_gauge_takes_four():
    no_tg = [n for n in NODES if n.node_type != "tide_gauge"]
    assert select_nodes("KSL-B3", no_tg, by_zone(no_tg)) == ["WQ-02", "SP-01", "WQ-01", "WQ-03"]


def test_select_nodes_uncovered_zone_is_empty_even_with_tide_gauge():
    assert select_nodes("KSL-E3", NODES, COVERAGE) == []


def test_select_nodes_skips_decommissioned():
    nodes = [N("WQ-02", "water_quality", 160.0, 250.0, status="decommissioned"), *NODES[2:]]
    assert "WQ-02" not in select_nodes("KSL-B3", nodes, coverage(nodes))


# ---- controller harness -----------------------------------------------------------------------------
class FakeMqtt:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def publish(self, topic: str, payload: bytes, *, qos: int = 1, retain: bool = False) -> None:
        parse_message("cmd", payload)  # every command is a valid bcs.cmd.v1
        self.sent.append({"topic": topic, **json.loads(payload)})

    def last_mode(self, node_id: str) -> str:
        return [c for c in self.sent if c["node_id"] == node_id][-1]["params"]["mode"]


class FakeRegistry:
    def __init__(self, nodes: list[N]) -> None:
        self._nodes = nodes

    def nodes(self) -> list[N]:
        return [n for n in self._nodes if n.status != "decommissioned"]

    def get(self, node_id: str) -> N | None:
        return next((n for n in self._nodes if n.id == node_id), None)


class Harness:
    def __init__(self, tmp_path: Path, nodes: list[N] = NODES) -> None:
        self.clock = ManualClock(T0)
        self.db = Database(tmp_path / "bcs.sqlite3", self.clock)
        self.db.migrate()
        self.repo = Repo(self.db)
        self.bus = EventBus(clock=self.clock)
        self.events = self.bus.subscribe(10000)
        settings = load_settings(REPO_ROOT, env_file=None)
        self.mqtt = FakeMqtt()
        self.ctl = TaskingController(
            self.repo, FakeRegistry(nodes), self.bus, self.clock, settings,
            site=SiteRegistry(settings.site), site_id="KSL",
        )  # fmt: skip
        self.ctl.attach(self.mqtt)

    def ack(self, cmd: dict[str, Any], status: str = "accepted", reason: str | None = None) -> Any:
        doc = {
            "schema": "bcs.ack.v1", "site_id": "KSL", "node_id": cmd["node_id"], "command_id": cmd["command_id"],
            "at": to_iso(self.clock.now()), "status": status, "reason": reason, "source": "simulated",
            "replay": False,
        }  # fmt: skip
        return self.ctl.on_ack(parse_message("ack", json.dumps(doc).encode()))

    def drained(self, type_: str) -> list[dict[str, Any]]:
        out = []
        while self.events._queue:
            e = self.events._queue.popleft()
            if e.type == type_:
                out.append(e.data)
        return out

    async def advance(self, seconds: float) -> None:
        self.clock.advance(seconds)
        await self.ctl.tick(self.clock.now())

    async def task(self, task_id: str) -> dict[str, Any]:
        return next(t for t in await self.ctl.list_tasks("all") if t.id == task_id).model_dump()


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


async def test_trigger_issues_set_mode_to_selected_nodes_with_demo_values(h: Harness):
    t = await h.ctl.trigger("KSL-B3", "zone_flag", "zone KSL-B3 flagged")
    assert t is not None and t.status == "issued" and t.node_ids == ["WQ-02", "SP-01", "WQ-01", "TG-01"]
    assert from_iso(t.expires_at) == T0 + timedelta(seconds=180) and t.duration_s == 180
    assert [c["node_id"] for c in h.mqtt.sent] == t.node_ids
    for c in h.mqtt.sent:
        assert c["topic"] == f"bcs/v1/KSL/nodes/{c['node_id']}/cmd" and c["task_id"] == t.id
        assert c["type"] == "set_mode" and c["params"] == {"mode": "investigation", "duration_s": 180}
        assert from_iso(c["expires_at"]) - from_iso(c["issued_at"]) == timedelta(seconds=30)
    assert all(c.ack_status == "pending" and c.retries == 0 for c in t.commands)
    assert [e["timeline"][0]["event"] for e in h.drained("task.updated")] == ["issued"]
    rows = h.repo.query("SELECT * FROM commands", table="commands")
    assert len(rows) == 4 and {r["task_id"] for r in rows} == {t.id}


async def test_first_accepted_ack_makes_the_task_active(h: Harness):
    t = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    await h.ack(h.mqtt.sent[0])
    got = await h.task(t.id)
    assert got["status"] == "active" and got["commands"][0]["ack_status"] == "accepted"
    assert got["commands"][0]["ack_at"] is not None
    assert [e["event"] for e in got["timeline"]] == ["issued", "acknowledged", "active"]


async def test_repeat_trigger_extends_and_recommands_nodes(h: Harness):
    a = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    await h.advance(60)
    b = await h.ctl.trigger("KSL-B3", "node_anomaly", "anomaly", node_ids=["WQ-02"])
    assert b.id == a.id and from_iso(b.expires_at) == T0 + timedelta(seconds=240)
    assert len(h.mqtt.sent) == 8 and h.mqtt.sent[-1]["params"]["duration_s"] == 180
    assert "extended" in [e.event for e in b.timeline] and len(await h.ctl.list_tasks("all")) == 1


async def test_anomaly_burst_is_coalesced_into_the_open_task(h: Harness):
    """A ramp or spikes fault at 2 s sampling: anomalies every 2 s must not re-command every node."""
    a = await h.ctl.trigger(None, "node_anomaly", "WQ-02 anomaly", node_ids=["WQ-02"])
    for c in list(h.mqtt.sent):
        await h.ack(c)
    sent = len(h.mqtt.sent)
    h.drained("task.updated")
    for _ in range(14):  # 28 s of anomalies: the end would move by less than one cooldown (30 s)
        await h.advance(2)
        b = await h.ctl.trigger(None, "node_anomaly", "WQ-02 anomaly", node_ids=["WQ-02"])
        assert b is not None and b.id == a.id
    got = await h.task(a.id)
    assert len(h.mqtt.sent) == sent  # no new commands, no retries
    assert from_iso(got["expires_at"]) == T0 + timedelta(seconds=180)
    assert "extended" not in [e["event"] for e in got["timeline"]]
    assert [e["event"] for e in got["timeline"]].count("coalesced") == 1  # one counted note, not 14
    assert len(h.drained("task.updated")) == 1  # only that note was rewritten and broadcast
    await h.advance(2)  # 30 s after the task was issued: the end moves by a full cooldown
    c = await h.ctl.trigger(None, "node_anomaly", "WQ-02 anomaly", node_ids=["WQ-02"])
    assert from_iso(c.expires_at) == T0 + timedelta(seconds=210) and len(h.mqtt.sent) == sent + 4
    assert [e.event for e in c.timeline].count("extended") == 1


async def test_superseded_pending_command_is_not_retried(h: Harness):
    a = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    first = [c["command_id"] for c in h.mqtt.sent]
    await h.advance(2)
    await h.ctl.trigger("KSL-B3", "manual", "operator", duration_s=600)  # extends: newer commands
    newest = [c["command_id"] for c in h.mqtt.sent[4:]]
    assert len(newest) == 4 and set(newest).isdisjoint(first)
    await h.advance(3)  # the first commands' retry falls due, but each has been superseded
    assert len(h.mqtt.sent) == 8
    await h.advance(2)  # the newest commands are still retried once
    assert sorted(c["command_id"] for c in h.mqtt.sent[8:]) == sorted(newest)
    got = await h.task(a.id)
    retried = {e["details"]["command_id"] for e in got["timeline"] if e["event"] == "retried"}
    assert retried == set(newest)


async def test_cooldown_follows_the_end_of_a_task_then_a_new_task_starts(h: Harness):
    a = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    await h.advance(181)
    assert (await h.task(a.id))["status"] == "expired"
    assert await h.ctl.trigger("KSL-B3", "zone_flag", "flag") is None
    await h.advance(30)
    b = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    assert b is not None and b.id != a.id


async def test_manual_task_ignores_cooldown(h: Harness):
    await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    await h.advance(181)
    assert await h.ctl.trigger("KSL-B3", "manual", "operator") is not None


async def test_completed_ack_at_expiry_completes_and_superseded_completion_does_not(h: Harness):
    t = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    first = h.mqtt.sent[0]
    await h.ack(first)
    await h.advance(60)
    await h.ctl.trigger("KSL-B3", "zone_flag", "flag")  # extends: WQ-02 gets a new command
    await h.ack(first, "completed", "superseded")
    await h.advance(181)
    assert (await h.task(t.id))["status"] == "expired"
    await h.ack(h.mqtt.sent[4], "completed")  # the node's latest command completes late
    got = await h.task(t.id)
    assert got["status"] == "completed" and got["timeline"][-1]["event"] == "completed"


async def test_unacked_command_retried_once_after_5s_then_no_ack(h: Harness):
    t = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    await h.advance(4)
    assert len(h.mqtt.sent) == 4
    await h.advance(1)
    assert len(h.mqtt.sent) == 8 and h.mqtt.sent[4]["command_id"] == h.mqtt.sent[0]["command_id"]
    await h.advance(10)
    assert len(h.mqtt.sent) == 8  # once only
    await h.advance(15)
    cmds = (await h.task(t.id))["commands"]
    assert all(c["retries"] == 1 and c["ack_status"] == "no_ack" for c in cmds)


async def test_catch_up_tick_counts_the_retry_and_marks_no_ack(h: Harness):
    t = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    h.clock.advance(5)
    h.clock.advance(31)
    cmds = (await h.task(t.id))["commands"]  # list_tasks ticks first
    assert all(c["retries"] == 1 and c["ack_status"] == "no_ack" for c in cmds)


async def test_cancel_returns_every_node_to_baseline_and_late_acks_never_revive(h: Harness):
    t = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    inv = list(h.mqtt.sent)
    c = await h.ctl.cancel(t.id)
    assert c.status == "cancelled" and c.cancelled_by == "operator"
    assert all(h.mqtt.last_mode(n) == "baseline" for n in t.node_ids)
    for cmd in inv:
        await h.ack(cmd, "accepted")  # late acks for the cancelled investigation
    got = await h.task(t.id)
    assert got["status"] == "cancelled"
    assert [c["ack_status"] for c in got["commands"][:4]] == ["released"] * 4
    await h.advance(40)  # the investigation commands are never retried
    assert all(h.mqtt.last_mode(n) == "baseline" for n in t.node_ids)
    assert [c["params"]["mode"] for c in h.mqtt.sent].count("investigation") == 4


async def test_cancel_unknown_or_ended_task_raises(h: Harness):
    from bcs_gs.tasking.controller import TaskConflict, TaskNotFound

    with pytest.raises(TaskNotFound):
        await h.ctl.cancel("nope")
    t = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    await h.ctl.cancel(t.id)
    with pytest.raises(TaskConflict):
        await h.ctl.cancel(t.id)


async def test_release_sends_baseline_and_marks_command_released(h: Harness):
    t = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    r = await h.ctl.release(t.id, "SP-01")
    assert h.mqtt.last_mode("SP-01") == "baseline" and r.status == "issued"
    sp = [c for c in r.commands if c.node_id == "SP-01"]
    assert sp[0].ack_status == "released" and sp[1].params == {"mode": "baseline"}
    assert r.timeline[-1].event == "released" and r.timeline[-1].node_id == "SP-01"
    for n in ("WQ-02", "WQ-01", "TG-01"):
        r = await h.ctl.release(t.id, n)
    assert r.status == "cancelled"


async def test_node_anomaly_tasks_the_nodes_zone(h: Harness):
    t = await h.ctl.trigger(None, "node_anomaly", "WQ-02 anomaly on do_mg_l", node_ids=["WQ-02"])
    assert t.zone_id == "KSL-B3" and t.trigger == "node_anomaly" and "WQ-02" in t.node_ids


async def test_uncovered_flagged_zone_creates_gap_not_task(h: Harness):
    assert await h.ctl.trigger("KSL-E3", "zone_flag", "flag") is None
    cov = h.drained("coverage.updated")
    assert cov and [g["zone_id"] for g in cov[-1]["gaps"]] == ["KSL-E3"]
    assert cov[-1]["gaps"][0]["id"] == "gap-KSL-E3"
    assert "KSL-E3" in h.ctl.zones_needing() and await h.ctl.list_tasks("all") == []


async def test_cancel_all_appends_reason(h: Harness):
    t = await h.ctl.trigger("KSL-B3", "zone_flag", "zone KSL-B3 flagged")
    await h.ctl.cancel_all("re-commissioned")
    got = await h.task(t.id)
    assert got["status"] == "cancelled" and got["reason"].endswith("re-commissioned")
    assert got["reason"].startswith("zone KSL-B3 flagged")


async def test_flag_and_anomaly_events_trigger_tasks(h: Harness):
    h.ctl.start()
    try:
        h.bus.publish("zone.flagged", {"capture_id": "c1", "zone_id": "KSL-B3", "flags": [
            {"kind": "canopy_loss", "value": 12.0, "threshold": 5.0}]})  # fmt: skip
        for _ in range(100):
            if await h.ctl.list_tasks("all"):
                break
            await asyncio.sleep(0.01)
        (t,) = await h.ctl.list_tasks("all")
        assert t.trigger == "zone_flag" and "canopy_loss" in t.reason
    finally:
        await h.ctl.stop()


async def test_manual_trigger_is_never_coalesced(h: Harness):
    a = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    await h.advance(2)  # well inside the 30 s coalescing window
    sent = len(h.mqtt.sent)
    b = await h.ctl.trigger("KSL-B3", "manual", "operator wants more", duration_s=182)
    assert b.id == a.id and len(h.mqtt.sent) == sent + 4
    assert from_iso(b.expires_at) == T0 + timedelta(seconds=184)
    assert [e.event for e in b.timeline].count("extended") == 1


async def test_coalesced_trigger_leaves_one_counted_timeline_note(h: Harness):
    a = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    for _ in range(3):
        await h.advance(1)
        b = await h.ctl.trigger("KSL-B3", "risk_high", "KSL-B3 risk high")
    notes = [e for e in b.timeline if e.event == "coalesced"]
    assert b.id == a.id and len(notes) == 1 and notes[0].details["trigger"] == "risk_high"
    assert notes[0].details["count"] == 3 and "KSL-B3" in notes[0].details["reason"]
    stored = h.repo.get("tasks", {"id": a.id})
    assert any(e["event"] == "coalesced" for e in stored["timeline"])


async def test_zones_needing_coverage_survive_a_restart(h: Harness, tmp_path: Path):
    await h.ctl.trigger("KSL-E3", "zone_flag", "flag")  # uncovered zone: no task, remembered
    h.ctl.note_zone_needing("KSL-D4")
    fresh = Harness(tmp_path)  # same database file, new controller
    await fresh.ctl.tick()
    assert fresh.ctl.zones_needing() == ["KSL-E3", "KSL-D4"]


async def test_cancel_starts_the_same_cooldown_as_a_normal_end(h: Harness):
    a = await h.ctl.trigger("KSL-B3", "zone_flag", "flag")
    await h.advance(10)
    await h.ctl.cancel(a.id)
    assert await h.ctl.trigger("KSL-B3", "zone_flag", "flag") is None
    assert await h.ctl.trigger("KSL-B3", "manual", "operator") is not None  # manual ignores it
