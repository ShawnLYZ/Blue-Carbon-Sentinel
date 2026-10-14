"""Deterministic headless scenario runner (addendum K4, design spec 13).

``load_script`` validates a K4 YAML script and reports problems with the 1-based line they are on.
``run_script`` drives a started :class:`~bcs_sim.runtime.Runtime`: steps run in ``at_s`` order, the clock
advances in 0.2 s ticks (``realtime=False``: the runner owns the clock; ``realtime=True``: it sleeps) and
``runtime.step`` is called on every tick.

Determinism: for a fixed seed and start time the published messages are identical except for the random
per-boot ``boot_id`` (random by design, so a restart is distinguishable). ``RunLog.published_digest`` hashes
every message a node published, as (topic, payload without ``boot_id``), in publish order.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml

from .clock import Clock
from .faults import KINDS as FAULT_KINDS
from .inspector import InspectorPacket
from .runtime import Runtime
from .scenarios import SCENARIOS, grid_zone_bounds

log = logging.getLogger("bcs_sim.runner")

TICK_S = 0.2
EPS = 1e-9
BEHAVIOURS = ("hold", "drift")
TOP_KEYS = {"name", "seed", "duration_s", "demo_time_scale", "fast_forward", "nodes", "steps"}
# action -> (required fields, optional fields); "at_s" and "action" are implied
ACTIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "apply_scenario": (("zone", "scenario"), ("ramp_s",)),
    "clear_scenario": (("zone",), ()),
    "set_value": (("node", "parameter", "value"), ("behaviour",)),
    "clear_value": (("node",), ("parameter",)),
    "inject_fault": (("node", "fault"), ("params",)),
    "clear_fault": (("node", "fault"), ()),
    "set_battery": (("node", "pct"), ()),
    "set_rssi": (("node", "dbm"), ()),
    "install_node": (("node_type", "e_m", "s_m"), ("node",)),
    "remove_node": (("node",), ()),
    "start_recording": ((), ("name",)),
    "stop_recording": ((), ()),
}


class ScriptError(Exception):
    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


@dataclass(frozen=True)
class Step:
    at_s: float
    action: str
    line: int
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Script:
    name: str
    seed: int
    duration_s: float
    demo_time_scale: bool = True
    fast_forward: float = 1.0
    nodes: dict[str, Any] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)


@dataclass
class StepResult:
    at_s: float
    action: str
    ok: bool
    detail: str = ""  # what was done, e.g. the fault kind or the zone
    error: str | None = None


@dataclass
class RunLog:
    steps: list[StepResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    published_digest: str = ""
    published_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---- loading -------------------------------------------------------------------------------------------
def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _line(node: yaml.Node) -> int:
    return node.start_mark.line + 1


def _mapping(node: yaml.Node, what: str) -> dict[str, tuple[yaml.Node, yaml.Node]]:
    if not isinstance(node, yaml.MappingNode):
        raise ScriptError(_line(node), f"{what} must be a mapping")
    out: dict[str, tuple[yaml.Node, yaml.Node]] = {}
    for k, v in node.value:
        if not isinstance(k, yaml.ScalarNode):
            raise ScriptError(_line(k), f"{what} has a key that is not plain text")
        out[k.value] = (k, v)
    return out


def _value(node: yaml.Node) -> Any:
    loader = yaml.SafeLoader("")
    try:
        return loader.construct_object(node, deep=True)
    except yaml.YAMLError as exc:
        raise ScriptError(_line(node), f"invalid YAML: {getattr(exc, 'problem', exc)}") from exc
    finally:
        loader.dispose()


def load_script(text: str) -> Script:
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise ScriptError(
            (mark.line + 1) if mark else 1, f"invalid YAML: {getattr(exc, 'problem', exc)}"
        ) from exc
    if root is None:
        raise ScriptError(1, "empty script")
    top = _mapping(root, "script")
    for key, (knode, _) in top.items():
        if key not in TOP_KEYS:
            raise ScriptError(_line(knode), f"unknown field '{key}'")

    def get(key: str, kind: str, default: Any = None, required: bool = False) -> tuple[Any, int]:
        if key not in top:
            if required:
                raise ScriptError(_line(root), f"missing required field '{key}'")
            return default, _line(root)
        vnode = top[key][1]
        v = _value(vnode)
        ok = {
            "str": isinstance(v, str) and v != "",
            "int": isinstance(v, int) and not isinstance(v, bool),
            "num": _is_num(v),
            "bool": isinstance(v, bool),
            "map": isinstance(v, dict),
        }[kind]
        if not ok:
            raise ScriptError(_line(vnode), f"'{key}' must be a {kind}")
        return v, _line(vnode)

    name, _ = get("name", "str", required=True)
    seed, _ = get("seed", "int", required=True)
    duration, dline = get("duration_s", "num", required=True)
    if duration <= 0:
        raise ScriptError(dline, "'duration_s' must be positive")
    demo, _ = get("demo_time_scale", "bool", True)
    ff, fline = get("fast_forward", "num", 1)
    if ff <= 0:
        raise ScriptError(fline, "'fast_forward' must be positive")
    nodes, _ = get("nodes", "map", {})
    if "steps" not in top:
        raise ScriptError(_line(root), "missing required field 'steps'")
    snode = top["steps"][1]
    if not isinstance(snode, yaml.SequenceNode):
        raise ScriptError(_line(snode), "'steps' must be a list")
    steps = [_load_step(item, float(duration)) for item in snode.value]
    steps.sort(key=lambda s: s.at_s)  # stable: same-offset steps keep their written order
    return Script(name, seed, float(duration), demo, float(ff), nodes, steps)


def _load_step(item: yaml.Node, duration_s: float) -> Step:
    line = _line(item)
    fields = _mapping(item, "step")
    for req in ("at_s", "action"):
        if req not in fields:
            raise ScriptError(line, f"step is missing '{req}'")
    at_node = fields["at_s"][1]
    at_s = _value(at_node)
    if not _is_num(at_s) or at_s < 0:
        raise ScriptError(_line(at_node), "'at_s' must be a number >= 0")
    if at_s > duration_s:
        raise ScriptError(_line(at_node), f"'at_s' {at_s:g} is after duration_s {duration_s:g}")
    action_node = fields["action"][1]
    action = _value(action_node)
    if action not in ACTIONS:
        raise ScriptError(_line(action_node), f"unknown action '{action}' (one of: {', '.join(ACTIONS)})")
    required, optional = ACTIONS[action]
    for key, (knode, _) in fields.items():
        if key not in ("at_s", "action", *required, *optional):
            raise ScriptError(_line(knode), f"'{action}' has no field '{key}'")
    for key in required:
        if key not in fields:
            raise ScriptError(line, f"'{action}' needs '{key}'")
    args = {k: _value(v) for k, (_, v) in fields.items() if k not in ("at_s", "action")}

    def bad(key: str, msg: str) -> ScriptError:
        return ScriptError(_line(fields[key][1]), msg)

    for key in ("node", "parameter", "name", "node_type", "scenario", "fault", "zone", "behaviour"):
        if key in args and not (isinstance(args[key], str) and args[key]):
            raise bad(key, f"'{key}' must be text")
    for key in ("value", "ramp_s", "pct", "dbm", "e_m", "s_m"):
        if key in args and not _is_num(args[key]):
            raise bad(key, f"'{key}' must be a number")
    if "zone" in args and args["zone"] not in grid_zone_bounds():
        raise bad("zone", f"unknown zone '{args['zone']}' (A1..E5)")
    if "scenario" in args and args["scenario"] not in SCENARIOS:
        raise bad("scenario", f"unknown scenario '{args['scenario']}' (one of: {', '.join(SCENARIOS)})")
    if "fault" in args and args["fault"] not in FAULT_KINDS:
        raise bad("fault", f"unknown fault '{args['fault']}' (one of: {', '.join(sorted(FAULT_KINDS))})")
    if "behaviour" in args and args["behaviour"] not in BEHAVIOURS:
        raise bad("behaviour", f"unknown behaviour '{args['behaviour']}' (hold or drift)")
    if "params" in args and not isinstance(args["params"], dict):
        raise bad("params", "'params' must be a mapping")
    if "ramp_s" in args and args["ramp_s"] < 0:
        raise bad("ramp_s", "'ramp_s' must be >= 0")
    if "pct" in args and not 0 <= args["pct"] <= 100:
        raise bad("pct", "'pct' must be between 0 and 100")
    return Step(float(at_s), action, line, args)


# ---- running -------------------------------------------------------------------------------------------
def _canonical(payload: Any, raw: bytes) -> bytes:
    """The payload with every ``boot_id`` removed (random per boot), as stable bytes."""
    if not isinstance(payload, (dict, list)):
        return raw  # malformed on purpose: hash it as sent

    def strip(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k != "boot_id"}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o

    return json.dumps(strip(payload), sort_keys=True, separators=(",", ":")).encode()


class _Digest:
    def __init__(self) -> None:
        self._h = hashlib.sha256()
        self.count = 0

    def __call__(self, pkt: InspectorPacket) -> None:
        if pkt.direction != "up":
            return
        self._h.update(pkt.topic.encode())
        self._h.update(b"\0")
        self._h.update(_canonical(pkt.payload, pkt.raw))
        self._h.update(b"\n")
        self.count += 1

    def hexdigest(self) -> str:
        return self._h.hexdigest()


def _node(rt: Runtime, node_id: str) -> Any:
    nr = rt.nodes.get(node_id)
    if nr is None:
        raise KeyError(f"unknown node {node_id}")
    return nr


def _execute(rt: Runtime, step: Step) -> str:
    a = step.args
    with rt.lock:
        match step.action:
            case "apply_scenario":
                rt.scenarios.apply(a["zone"], a["scenario"], a.get("ramp_s"))
                return f"{a['scenario']}@{a['zone']}"
            case "clear_scenario":
                rt.scenarios.clear(a["zone"])
                return a["zone"]
            case "set_value":
                _node(rt, a["node"])
                rt.overrides.set(a["node"], a["parameter"], a["value"], a.get("behaviour", "hold"))
                return f"{a['node']}.{a['parameter']}"
            case "clear_value":
                _node(rt, a["node"])
                rt.overrides.clear(a["node"], a.get("parameter"))
                return a["node"]
            case "inject_fault":
                rt.faults(a["node"]).inject(a["fault"], a.get("params"))  # KeyError if unknown node
                return a["fault"]
            case "clear_fault":
                rt.faults(a["node"]).clear(a["fault"])
                return a["fault"]
            case "set_battery":
                _node(rt, a["node"]).node.battery.set(a["pct"])
                return a["node"]
            case "set_rssi":
                _node(rt, a["node"]).node.rssi_dbm = float(a["dbm"])
                return a["node"]
            case "install_node":
                install = getattr(rt.gs, "install_node", None)
                if install is None:
                    raise RuntimeError("this Ground Station client cannot install nodes")
                node_id = install(a["node_type"], a["e_m"], a["s_m"], a.get("node"))
            case "remove_node":
                remove = getattr(rt.gs, "remove_node", None)
                if remove is None:
                    raise RuntimeError("this Ground Station client cannot remove nodes")
                remove(a["node"])
                node_id = a["node"]
            case "start_recording":
                rt.recorder.start(a.get("name") or "scenario")
                return a.get("name") or "scenario"
            case "stop_recording":
                return rt.recorder.stop().id
            case _:  # pragma: no cover - load_script rejects it
                raise ValueError(f"unknown action {step.action}")
    rt.on_registry_change()  # install / remove: pick the registry change up
    return str(node_id)


def _setup(rt: Runtime, script: Script) -> list[str]:
    errors: list[str] = []
    if rt.demo_time_scale != script.demo_time_scale:
        errors.append(
            f"script demo_time_scale={script.demo_time_scale} but the runtime was built with {rt.demo_time_scale}"
        )
    if script.fast_forward != 1:
        rt.env.set_fast_forward(script.fast_forward)
    for node_id, over in script.nodes.items():
        pos = (over or {}).get("position")
        try:
            nr = _node(rt, node_id)
            if pos:
                nr.node.e_m, nr.node.s_m = float(pos["e_m"]), float(pos["s_m"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"nodes.{node_id}: {exc}")
    return errors


def run_script(script: Script, runtime: Runtime, clock: Clock, *, realtime: bool) -> RunLog:
    """Run ``script`` on a started ``runtime``. Step failures are collected in ``errors``, not raised.

    ``realtime=False``: ``clock`` is advanced 0.2 s per tick (and ``runtime.clock`` with it when that is a
    different manual clock, which must then start at the same instant). ``realtime=True``: ``clock`` is a
    wall clock and the runner sleeps between ticks.
    """
    out = RunLog()
    digest = _Digest()
    runtime.inspector.add_listener(digest)
    try:
        out.errors += _setup(runtime, script)
        rt_clock = runtime.clock
        if (
            not realtime
            and rt_clock is not clock
            and (not hasattr(rt_clock, "advance") or rt_clock.now() != clock.now())
        ):
            out.errors.append(
                "the runtime's clock must be the runner's clock or a manual clock at the same time"
            )
            return out
        pending = list(script.steps)
        ticks = round(script.duration_s / TICK_S)
        wall0 = time.monotonic()
        for i in range(ticks + 1):
            t = i * TICK_S
            while pending and pending[0].at_s <= t + EPS:
                step = pending.pop(0)
                try:
                    res = StepResult(step.at_s, step.action, True, _execute(runtime, step))
                except Exception as exc:  # noqa: BLE001 - a bad step is reported, the run goes on
                    msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
                    res = StepResult(step.at_s, step.action, False, error=str(msg))
                    out.errors.append(f"t={step.at_s:g}s {step.action} (line {step.line}): {msg}")
                out.steps.append(res)
            try:
                runtime.step(clock.now())
            except Exception as exc:
                log.exception("runtime step failed")
                out.errors.append(f"t={t:.1f}s runtime step failed: {exc}")
                break
            if realtime:
                time.sleep(max(0.0, wall0 + (i + 1) * TICK_S - time.monotonic()))
            else:
                clock.advance(TICK_S)  # type: ignore[attr-defined]
                if rt_clock is not clock:
                    rt_clock.advance(TICK_S)  # type: ignore[attr-defined]
    finally:
        runtime.inspector.remove_listener(digest)
        out.published_digest = digest.hexdigest()
        out.published_count = digest.count
    return out
