"""Node registry (addendum A4, A8, F1, G6, H2, J2): devices, their keys, broker identities and history.

Methods are synchronous and may block on the broker, so async callers run them in a worker thread.
Every change writes ``device_history`` and publishes ``node.registry`` on the EventBus. Key hashes
live only in ``device_keys``; a plaintext key is returned once to the caller and never stored or logged.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any

from bcs_protocol.timefmt import to_iso

from bcs_gs.core.clock import Clock
from bcs_gs.core.events import EventBus
from bcs_gs.core.ids import uuid7
from bcs_gs.nodes.broker_admin import BrokerAdmin
from bcs_gs.nodes.keys import hash_key, new_key
from bcs_gs.site.registry import SiteRegistry
from bcs_gs.store.repo import Repo

log = logging.getLogger("bcs_gs.nodes")

CAMERA_ID = "CAM-01"
PREFIXES = {"water_quality": "WQ", "soil_probe": "SP", "tide_gauge": "TG"}
SOURCES = ("simulated", "hardware")


@dataclass(frozen=True)
class NodeRow:
    id: str
    kind: str
    node_type: str | None
    source: str
    site_id: str
    e_m: float | None
    s_m: float | None
    lat: float | None
    lng: float | None
    u_px: float | None
    v_px: float | None
    zone_id: str | None
    status: str
    mode: str | None
    interval_s: int | None
    fw_version: str | None
    boot_id: str | None
    installed_at: str | None
    decommissioned_at: str | None
    last_seen_at: str | None
    commissioning_run_id: str | None
    updated_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> NodeRow:
        return cls(**{f: row.get(f) for f in cls.__dataclass_fields__})

    @property
    def zone_label(self) -> str | None:
        return self.zone_id.split("-", 1)[1] if self.zone_id else None


class NodeRegistry:
    def __init__(
        self,
        repo: Repo,
        broker_admin: BrokerAdmin | None,
        bus: EventBus,
        site: SiteRegistry,
        clock: Clock,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._repo, self._broker, self._bus = repo, broker_admin, bus
        self._site, self._clock = site, clock
        self._loop = loop  # the loop that serves /ws/events; events from other threads hop onto it
        self._lock = threading.RLock()
        self._site_id = site.site().id

    # ---- reads -------------------------------------------------------------------------------
    def nodes(self, include_decommissioned: bool = False) -> list[NodeRow]:
        sql = "SELECT * FROM devices WHERE kind = 'sentinel_node'"
        if not include_decommissioned:
            sql += " AND status != 'decommissioned'"
        rows = self._repo.query(sql + " ORDER BY id", table="devices")
        return [NodeRow.from_row(r) for r in rows]

    def get(self, node_id: str) -> NodeRow | None:
        row = self._repo.get("devices", {"id": node_id})
        return NodeRow.from_row(row) if row else None

    def next_id(self, node_type: str) -> str:
        """The next number of the type's sequence; decommissioned numbers stay taken (F1)."""
        prefix = self._prefix(node_type)
        rows = self._repo.query("SELECT id FROM devices WHERE id LIKE ?", (f"{prefix}-%",), table="devices")
        used = [int(r["id"].split("-", 1)[1]) for r in rows if r["id"].split("-", 1)[1].isdigit()]
        return f"{prefix}-{max(used, default=0) + 1:02d}"

    # ---- writes ------------------------------------------------------------------------------
    def ensure_camera(self) -> None:
        """Register ``CAM-01`` as a camera device. It has no generated key: its token comes from .env (A4, L7)."""
        with self._lock:
            if self._repo.get("devices", {"id": CAMERA_ID}) is not None:
                return
            now = to_iso(self._clock.now())
            self._repo.upsert(
                "devices",
                {
                    "id": CAMERA_ID, "kind": "camera", "node_type": None, "source": "hardware",
                    "site_id": self._site_id, "status": "unknown", "installed_at": now, "updated_at": now,
                },
            )  # fmt: skip

    def install(
        self,
        node_type: str,
        source: str,
        e_m: float,
        s_m: float,
        *,
        commissioning_run_id: str | None = None,
        emit: bool = True,
    ) -> tuple[NodeRow, str]:
        """Create a node, its broker identity and key. Returns the node and its plaintext key (once).
        ``emit=False`` leaves the ``node.registry`` event to the caller (a commissioning run sends one)."""
        if source not in SOURCES:
            raise ValueError(f"unknown source {source!r}")
        with self._lock:
            node_id = self.next_id(node_type)
            pos = self._position(e_m, s_m)  # raises ValueError outside the site, before anything exists
            key = new_key()
            now = to_iso(self._clock.now())
            if self._broker is not None:
                self._broker.ensure_node(node_id, self._site_id, key)
            with self._repo.transaction():
                self._repo.upsert(
                    "devices",
                    {
                        "id": node_id, "kind": "sentinel_node", "node_type": node_type, "source": source,
                        "site_id": self._site_id, **pos, "status": "unknown", "installed_at": now,
                        "commissioning_run_id": commissioning_run_id, "updated_at": now,
                    },
                )  # fmt: skip
                self._repo.upsert(
                    "device_keys",
                    {"device_id": node_id, "key_hash": hash_key(key), "created_at": now, "rotations": 0},
                )
                self._history(node_id, "installed", {"source": source, "to": {"e_m": e_m, "s_m": s_m}})
            row = self._require(node_id)
        if emit:
            self._emit("installed", [node_id], commissioning_run_id)
        return row, key

    def move(self, node_id: str, e_m: float, s_m: float) -> NodeRow:
        with self._lock:
            old = self._require_active(node_id)
            pos = self._position(e_m, s_m)
            now = to_iso(self._clock.now())
            with self._repo.transaction():
                self._update_device(node_id, **pos, updated_at=now)
                self._history(
                    node_id, "moved",
                    {"from": {"e_m": old.e_m, "s_m": old.s_m}, "to": {"e_m": e_m, "s_m": s_m}},
                )  # fmt: skip
            row = self._require(node_id)
        self._emit("moved", [node_id])
        return row

    def recommission(self, node_id: str, e_m: float, s_m: float, *, commissioning_run_id: str) -> NodeRow:
        """Move a node to its position from a commissioning run and log ``re_commissioned``. No event:
        the commissioning run publishes one ``node.registry`` for all its nodes."""
        with self._lock:
            old = self._require_active(node_id)
            pos = self._position(e_m, s_m)
            now = to_iso(self._clock.now())
            with self._repo.transaction():
                self._update_device(node_id, **pos, commissioning_run_id=commissioning_run_id, updated_at=now)
                self._history(
                    node_id, "re_commissioned",
                    {
                        "from": {"e_m": old.e_m, "s_m": old.s_m}, "to": {"e_m": e_m, "s_m": s_m},
                        "commissioning_run_id": commissioning_run_id,
                    },
                )  # fmt: skip
            return self._require(node_id)

    def decommission(self, node_id: str) -> NodeRow:
        with self._lock:
            self._require_active(node_id)
            if self._broker is not None:
                self._broker.disable_node(node_id)
            now = to_iso(self._clock.now())
            with self._repo.transaction():
                self._update_device(
                    node_id, status="decommissioned", decommissioned_at=now, updated_at=now
                )
                self._history(node_id, "decommissioned", {})
            row = self._require(node_id)
        self._emit("decommissioned", [node_id])
        return row

    def regenerate_key(self, node_id: str) -> str:
        with self._lock:
            self._require_active(node_id)
            key = self._rotate(node_id)
        self._emit("key_regenerated", [node_id])
        return key

    def provision_simulated(self, node_ids: list[str] | None = None, *, emit: bool = True) -> dict[str, str]:
        """Regenerate the keys of active simulated nodes (all, or those named) and return them once.
        Hardware nodes and unknown or decommissioned IDs are skipped (A4).

        ``emit=False`` for the simulator's own credential fetch (``/internal/sim/credentials``): it already
        holds the new keys, and a ``key_regenerated`` event would make its registry watcher fetch again,
        rotating the key forever."""
        with self._lock:
            targets = [n.id for n in self.nodes() if n.source == "simulated"]
            if node_ids is not None:
                wanted = set(node_ids)
                targets = [t for t in targets if t in wanted]
            keys = {nid: self._rotate(nid) for nid in targets}
        if keys and emit:
            self._emit("key_regenerated", list(keys))
        return keys

    # ---- internals ---------------------------------------------------------------------------
    @staticmethod
    def _prefix(node_type: str) -> str:
        try:
            return PREFIXES[node_type]
        except KeyError:
            raise ValueError(f"unknown node type {node_type!r}") from None

    def _position(self, e_m: float, s_m: float) -> dict[str, Any]:
        zone_id = self._site.zone_at(e_m, s_m)
        lng, lat = self._site.metres_to_lnglat(e_m, s_m)
        u, v = self._site.metres_to_raster(e_m, s_m)
        return {"e_m": e_m, "s_m": s_m, "lat": lat, "lng": lng, "u_px": u, "v_px": v, "zone_id": zone_id}

    def _require(self, node_id: str) -> NodeRow:
        row = self.get(node_id)
        if row is None:
            raise KeyError(f"unknown device {node_id!r}")
        return row

    def _require_active(self, node_id: str) -> NodeRow:
        row = self._require(node_id)
        if row.kind != "sentinel_node":
            raise ValueError(f"{node_id} is not a Sentinel Node")
        if row.status == "decommissioned":
            raise ValueError(f"{node_id} is decommissioned")
        return row

    def _rotate(self, node_id: str) -> str:
        """New key: broker first (so a failure leaves the old hash valid), then the hash and history."""
        key = new_key()
        if self._broker is not None:
            self._broker.ensure_node(node_id, self._site_id, key)
        now = to_iso(self._clock.now())
        old = self._repo.get("device_keys", {"device_id": node_id})
        with self._repo.transaction():
            self._repo.upsert(
                "device_keys",
                {
                    "device_id": node_id, "key_hash": hash_key(key),
                    "created_at": now, "rotations": (old["rotations"] + 1) if old else 0,
                },
            )  # fmt: skip
            self._history(node_id, "key_regenerated", {})
        return key

    def _update_device(self, node_id: str, **changes: Any) -> None:
        row = self._repo.get("devices", {"id": node_id})
        if row is None:
            raise KeyError(f"unknown device {node_id!r}")
        self._repo.upsert("devices", {**row, **changes})

    def _history(self, node_id: str, change: str, details: dict[str, Any]) -> None:
        self._repo.insert(
            "device_history",
            {
                "id": uuid7(), "device_id": node_id, "at": to_iso(self._clock.now()),
                "change": change, "details": details,
            },
        )  # fmt: skip

    def _emit(self, change: str, node_ids: list[str], commissioning_run_id: str | None = None) -> None:
        data: dict[str, Any] = {"change": change, "node_ids": node_ids}
        if commissioning_run_id:
            data["commissioning_run_id"] = commissioning_run_id
        loop = self._loop
        if loop is not None and loop.is_running() and not _on_loop(loop):
            loop.call_soon_threadsafe(self._bus.publish, "node.registry", data)
        else:
            self._bus.publish("node.registry", data)


def _on_loop(loop: asyncio.AbstractEventLoop) -> bool:
    try:
        return asyncio.get_running_loop() is loop
    except RuntimeError:
        return False
