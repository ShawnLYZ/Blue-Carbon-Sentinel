"""Reference edge logic (design spec 13): the behaviour future real firmware copies.

Receives FINAL readings (the readings pipeline lives in ``nodes.models``). Responsibilities: sampling
schedule (baseline / investigation, battery aware), anomaly flags (spike, threshold, stuck, battery),
command handling with acknowledgements, and config application.

Conventions: telemetry consumes ``node.seq`` (the next telemetry sequence number) and increments it.
Events have their own per-boot counter, ``node.event_seq``: every event (boot, config_applied,
anomaly, threshold, stuck, battery_low) takes the next value when it is created, so the G3 dedupe key
(node, boot, seq) is unique per event. Both counters restart at 0 on boot.
Spike and threshold flags are per-sample; ``stuck`` and ``battery`` flags persist while the condition
holds, but their events fire only on the rising edge. Events raised outside ``sample`` (config_applied,
boot) are queued and collected with ``drain_events``.
"""

from __future__ import annotations

import statistics
from collections import deque
from datetime import datetime, timedelta

from bcs_protocol.generated.ack_schema import Ack
from bcs_protocol.generated.cmd_schema import Command
from bcs_protocol.generated.config_schema import NodeConfig
from bcs_protocol.generated.event_schema import NodeEvent
from bcs_protocol.generated.telemetry_schema import Telemetry
from bcs_protocol.timefmt import from_iso, to_iso

from .clock import Clock
from .nodes.models import SimNode

MIN_Z_HISTORY = 5
_DEFAULT_EPS = 1e-3


class EdgeLogic:
    def __init__(self, node: SimNode, config: NodeConfig, clock: Clock) -> None:
        self.node = node
        self.config = config
        self.clock = clock
        self.mode = "baseline"
        self.last: Telemetry | None = None
        self._last_sample: datetime | None = None
        self._mode_until: datetime | None = None
        self._mode_command: str | None = None
        self._investigation_interval: float | None = None
        self._windows: dict[str, deque[float]] = {}
        self._critical: dict[str, bool] = {}
        self._stuck: set[str] = set()
        self._battery_low = False
        self._events: list[NodeEvent] = []
        node.boot(clock.now())

    # -- schedule ---------------------------------------------------------------------------
    def _low(self) -> bool:
        return self.node.battery.pct < self.config.battery_low_pct

    def interval_s(self) -> float:
        if self.mode == "investigation":
            return float(self._investigation_interval or self.config.investigation_interval_s)
        base = float(self.config.baseline_interval_s)
        return base * 2 if self._low() else base

    def due(self, now: datetime) -> bool:
        if self._last_sample is None:
            return True
        return (now - self._last_sample).total_seconds() >= self.interval_s()

    # -- messages ---------------------------------------------------------------------------
    def _event(
        self, kind: str, at: datetime, parameter=None, value=None, score=None, details=None
    ) -> NodeEvent:
        seq = self.node.event_seq
        self.node.event_seq += 1
        return NodeEvent.model_validate(
            {
                "schema": "bcs.event.v1",
                "site_id": self.node.site_id,
                "node_id": self.node.node_id,
                "boot_id": self.node.boot_id,
                "seq": seq,
                "at": to_iso(at),
                "kind": kind,
                "parameter": parameter,
                "value": value,
                "score": score,
                "details": details or {},
                "source": "simulated",
                "replay": False,
            }
        )

    def _ack(self, command_id: str, status: str, now: datetime, reason: str | None = None) -> Ack:
        return Ack.model_validate(
            {
                "schema": "bcs.ack.v1",
                "site_id": self.node.site_id,
                "node_id": self.node.node_id,
                "command_id": command_id,
                "at": to_iso(now),
                "status": status,
                "reason": reason,
                "source": "simulated",
                "replay": False,
            }
        )

    def boot_event(self, at: datetime, reason: str = "power_on") -> NodeEvent:
        """The ``boot`` event a transport announces on connect (not queued)."""
        return self._event("boot", at, details={"reason": reason})

    def drain_events(self) -> list[NodeEvent]:
        out, self._events = self._events, []
        return out

    # -- sampling ---------------------------------------------------------------------------
    def _window(self, key: str) -> deque[float]:
        w = self._windows.get(key)
        if w is None or w.maxlen != self.config.anomaly.window:
            w = deque(w or (), maxlen=self.config.anomaly.window)
            self._windows[key] = w
        return w

    def _eps(self, key: str) -> float:
        return getattr(self.config.anomaly.stuck_epsilon, key, None) or _DEFAULT_EPS

    def _is_critical(self, key: str, v: float) -> bool:
        """Critical bands are thresholds (G3): a value below ``min`` or above ``max`` is critical."""
        band = getattr(self.config.critical_bands, key, None)
        if band is None:
            return False
        return (band.min is not None and v < band.min) or (band.max is not None and v > band.max)

    def sample(self, readings: dict, health: dict, now: datetime) -> tuple[Telemetry, list[NodeEvent]]:
        a = self.config.anomaly
        seq = self.node.seq
        flags: list[dict] = []
        # Event arguments, grouped by kind; events (and their seqs) are created in this order at the end.
        spikes: list[tuple] = []
        thresholds: list[tuple] = []
        stucks: list[tuple] = []
        for key, v in readings.items():
            w = self._window(key)
            if len(w) >= MIN_Z_HISTORY:
                sd = max(statistics.pstdev(w), self._eps(key))
                z = (v - statistics.fmean(w)) / sd
                if abs(z) > a.z_threshold:
                    flags.append({"parameter": key, "kind": "spike", "score": round(z, 3)})
                    spikes.append(("anomaly", now, key, v, round(z, 3), {"z": round(z, 3)}))
            w.append(v)
            # ``threshold`` fires on the transition from within [min, max] to outside it, per parameter.
            critical = self._is_critical(key, v)
            if critical and not self._critical.get(key, False):
                flags.append({"parameter": key, "kind": "threshold", "score": v})
                thresholds.append(("threshold", now, key, v, v, {}))
            self._critical[key] = critical
            if len(w) >= a.stuck_window:
                recent = list(w)[-a.stuck_window :]
                spread = max(recent) - min(recent)
                if spread < self._eps(key):
                    flags.append({"parameter": key, "kind": "stuck", "score": round(spread, 6)})
                    if key not in self._stuck:
                        self._stuck.add(key)
                        stucks.append(("stuck", now, key, v, round(spread, 6), {}))
                else:
                    self._stuck.discard(key)
        extra: list[tuple] = []
        low = self._low()
        if low:
            deficit = round(self.config.battery_low_pct - self.node.battery.pct, 3)
            flags.append({"parameter": "battery_pct", "kind": "battery", "score": deficit})
            if not self._battery_low:
                extra.append(("battery_low", now, "battery_pct", self.node.battery.pct, deficit, {}))
        self._battery_low = low

        tel = Telemetry.model_validate(
            {
                "schema": "bcs.telemetry.v1",
                "site_id": self.node.site_id,
                "node_id": self.node.node_id,
                "node_type": self.node.node_type,
                "boot_id": self.node.boot_id,
                "seq": seq,
                "sampled_at": to_iso(now),
                "mode": self.mode,
                "readings": readings,
                "health": health,
                "flags": flags,
                "source": "simulated",
                "replay": False,
            }
        )
        self.node.seq += 1
        self._last_sample = now
        self.node.battery.drain(1, 1)
        self.last = tel
        events = [self._event(*args) for args in spikes + thresholds + stucks + extra]
        return tel, events

    # -- commands ---------------------------------------------------------------------------
    def apply_config(self, cfg: NodeConfig) -> NodeEvent:
        self.config = cfg
        for key in list(self._windows):
            self._window(key)
        ev = self._event(
            "config_applied",
            self.clock.now(),
            details={
                "config_version": cfg.config_version,
                "baseline_interval_s": cfg.baseline_interval_s,
                "investigation_interval_s": cfg.investigation_interval_s,
            },
        )
        self._events.append(ev)
        return ev

    def _to_baseline(self) -> None:
        self.mode = "baseline"
        self._mode_until = None
        self._mode_command = None
        self._investigation_interval = None

    def handle(self, cmd: Command, now: datetime) -> list[Ack]:
        cid = cmd.command_id
        if from_iso(cmd.expires_at) < now:
            return [self._ack(cid, "expired", now, "command expired before delivery")]
        p = cmd.params
        if cmd.type == "ping":
            return [self._ack(cid, "accepted", now, "pong")]
        if cmd.type == "reboot":
            ack = self._ack(cid, "accepted", now, "rebooting")
            self._to_baseline()
            self._windows.clear()
            self._critical.clear()
            self._stuck.clear()
            self._battery_low = False
            self._last_sample = None
            self.node.boot(now)
            self._events.append(self._event("boot", now, details={"reason": "reboot_command"}))
            return [ack]
        if cmd.type == "set_mode":
            mode = p.get("mode")
            if mode not in ("baseline", "investigation"):
                return [self._ack(cid, "rejected", now, "invalid mode")]
            out: list[Ack] = []
            prev = self._mode_command
            if mode == "baseline":
                self._to_baseline()
                if prev and prev != cid:
                    out.append(self._ack(prev, "completed", now, "superseded"))
                return out + [self._ack(cid, "accepted", now)]
            dur = p.get("duration_s")
            if not isinstance(dur, int | float) or isinstance(dur, bool) or dur <= 0:
                return [self._ack(cid, "rejected", now, "investigation requires duration_s > 0")]
            if prev and prev != cid:  # a retry of the running command (same ID) does not supersede it
                out.append(self._ack(prev, "completed", now, "superseded"))
            self.mode = "investigation"
            self._mode_until = now + timedelta(seconds=float(dur))
            self._mode_command = cid
            iv = p.get("interval_s")
            self._investigation_interval = float(iv) if isinstance(iv, int | float) and iv > 0 else None
            return out + [self._ack(cid, "accepted", now)]
        if cmd.type == "set_config":
            try:
                merged = self.config.model_dump(by_alias=True) | dict(p)
                cfg = NodeConfig.model_validate(merged)
            except Exception as exc:  # noqa: BLE001 - any validation failure rejects the command
                return [self._ack(cid, "rejected", now, f"invalid config: {str(exc)[:120]}")]
            self.apply_config(cfg)
            return [self._ack(cid, "accepted", now)]
        return [self._ack(cid, "rejected", now, "unknown command type")]

    def tick(self, now: datetime) -> list[Ack]:
        if self.mode == "investigation" and self._mode_until is not None and now >= self._mode_until:
            cid = self._mode_command
            self._to_baseline()
            if cid:
                return [self._ack(cid, "completed", now)]
        return []
