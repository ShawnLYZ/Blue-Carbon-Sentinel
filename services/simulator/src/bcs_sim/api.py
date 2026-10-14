"""Sentinel Simulator control routes (addendum K1), under ``/api/v1``.

Every route that touches the simulated world needs the running ``Runtime`` (it starts once the Ground
Station answers); until then they answer ``503 upstream_unavailable``. Runtime work runs off the event loop
(``asyncio.to_thread``) under ``Runtime.lock``.

Lifecycle routes delegate to the Ground Station's public node routes (``POST /nodes``, ``/nodes/{id}/move``,
``/nodes/{id}/decommission``): the Ground Station owns the registry, so its answer, error or not, is passed
through unchanged (status and I1 body). The simulator then reloads the registry so the node starts, moves or
stops at once (the ``node.registry`` watcher would also pick it up).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from bcs_protocol.timefmt import to_iso
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import REPO_ROOT, SimSettings
from .environment import RANGES
from .errors import ApiError, envelope
from .faults import KINDS as FAULT_KINDS
from .gs_client import GsError
from .recorder import DEFAULT_SESSIONS_DIR, KIND, sidecar_path
from .runner import ScriptError, load_script, run_script
from .runtime import Runtime
from .scenarios import DEFAULT_RAMP_S, NODE_KEYS, RECOVERY_TAU_S, SCENARIOS, ScenarioDef, reach_factor

log = logging.getLogger("bcs_sim.api")

SCENARIOS_DIR = REPO_ROOT / "services" / "simulator" / "scenarios"
_SCRIPT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_ZONE_PREFIX = re.compile(r"^[A-Za-z0-9]+-(?=[A-Z][0-9]+$)")  # "KSL-B3" -> "B3"
NOT_STARTED = "The simulator is not running yet: it starts once the Ground Station answers."
FAULT_PARAMETER_KINDS = ("stuck", "spikes", "drift")


# ---- request bodies ------------------------------------------------------------------------------------
class ScenarioBody(BaseModel):
    scenario: str
    ramp_s: float | None = Field(None, ge=0, le=3600)


class OverrideBody(BaseModel):
    parameter: str
    value: float
    behaviour: Literal["hold", "drift"] = "hold"


class HealthBody(BaseModel):
    battery_pct: float | None = Field(None, ge=0, le=100)
    rssi_dbm: float | None = Field(None, ge=-120, le=0)


class FaultBody(BaseModel):
    kind: str
    params: dict[str, Any] | None = None


class TideBody(BaseModel):
    enabled: bool | None = None
    mean_cm: float | None = Field(None, ge=-500, le=500)
    amplitude_cm: float | None = Field(None, ge=0, le=500)
    spring_neap: bool | None = None


class NatureBody(BaseModel):
    tide: TideBody | None = None
    diurnal: bool | None = None
    noise: bool | None = None
    fast_forward: float | None = Field(None, gt=0, le=10000)


class RecordingBody(BaseModel):
    name: str = Field("session", min_length=1, max_length=80)


class ScenarioRunBody(BaseModel):
    script: str | None = Field(None, max_length=200_000)
    name: str | None = None
    seed: int | None = None


# ---- scenario runs -------------------------------------------------------------------------------------
@dataclass
class ScenarioRun:
    run_id: str
    name: str
    seed: int
    requested_seed: int | None
    started_at: str
    status: Literal["running", "finished", "failed"] = "running"
    finished_at: str | None = None
    log: dict[str, Any] | None = None
    error: str | None = None
    note: str | None = None

    def view(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "name": self.name,
            "seed": self.seed,
            "requested_seed": self.requested_seed,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log": self.log,
            "error": self.error,
            "note": self.note,
        }


@dataclass
class SimContext:
    """What the routes and the ``/ws`` hub share. The runtime is ``app.state.runtime`` (tests) or the
    supervisor's (``bcs-sim run``), looked up on every use because the supervisor starts it later."""

    settings: SimSettings
    state: Any  # app.state
    runs: dict[str, ScenarioRun] = field(default_factory=dict)
    replay_session: dict[str, str] = field(default_factory=dict)  # session path -> session id
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def runtime(self) -> Runtime | None:
        rt = getattr(self.state, "runtime", None)
        if rt is not None:
            return rt
        sup = getattr(self.state, "runtime_supervisor", None)
        return getattr(sup, "runtime", None) if sup is not None else None

    @property
    def last_error(self) -> str | None:
        sup = getattr(self.state, "runtime_supervisor", None)
        return getattr(sup, "last_error", None) if sup is not None else None

    def running_run(self) -> str | None:
        with self.lock:
            return next((r.run_id for r in self.runs.values() if r.status == "running"), None)


def ctx_of(request: Request) -> SimContext:
    return request.app.state.sim


def need_runtime(ctx: SimContext) -> Runtime:
    rt = ctx.runtime
    if rt is None or not rt.started:
        raise ApiError("upstream_unavailable", 503, NOT_STARTED, {"last_error": ctx.last_error})
    return rt


async def locked(rt: Runtime, fn: Callable[[], Any]) -> Any:
    def call() -> Any:
        with rt.lock:
            return fn()

    return await asyncio.to_thread(call)


# ---- views ---------------------------------------------------------------------------------------------
def scenario_view(sid: str, d: ScenarioDef) -> dict[str, Any]:
    keys = scenario_keys(d)
    return {
        "id": sid,
        "offsets": dict(d.offsets),
        "night_offsets": dict(d.night_offsets),
        "fraction_day": d.fraction_day,
        "fraction_night": d.fraction_night,
        "key_tau_s": dict(d.key_tau_s),
        "default_ramp_s": RECOVERY_TAU_S if sid == "recovery" else DEFAULT_RAMP_S,
        "node_types": sorted(t for t, ks in NODE_KEYS.items() if keys & set(ks)),
    }


def scenario_keys(d: ScenarioDef) -> set[str]:
    """The G4 keys a scenario changes (low oxygen's saturation-fraction target changes DO)."""
    keys = set(d.offsets) | set(d.night_offsets)
    if d.fraction_day is not None or d.fraction_night is not None:
        keys.add("do_mg_l")
    return keys


def node_views(rt: Runtime) -> list[dict[str, Any]]:
    return [v.model_dump(mode="json") for v in rt.state()]


def node_view(rt: Runtime, node_id: str) -> dict[str, Any]:
    return next(n for n in node_views(rt) if n["node_id"] == node_id)


def zone_scenarios(rt: Runtime) -> dict[str, Any]:
    return {
        label: {"scenario": a.scenario, "started_at": to_iso(a.started), "ramp_s": a.ramp_s}
        for label, a in sorted(rt.scenarios.active().items())
    }


def replay_view(ctx: SimContext, rt: Runtime) -> dict[str, Any] | None:
    st = rt.replayer.status()
    if st is None:
        return None
    return {**st, "session_id": ctx.replay_session.get(st["path"])}


def broker_connected(rt: Runtime) -> bool:
    return any(nr.link.connected for nr in rt.nodes.values())


def full_state(ctx: SimContext) -> dict[str, Any]:
    """``GET /state`` (K1). Without a runtime: the empty skeleton."""
    rt = ctx.runtime
    if rt is None or not rt.started:
        return {
            "broker_connected": False,
            "demo_time_scale": ctx.settings.demo_time_scale == "on",
            "fast_forward": 1,
            "nature": {},
            "nodes": [],
            "zone_scenarios": {},
            "recording": None,
            "replay": None,
        }
    with rt.lock:
        return {
            "broker_connected": broker_connected(rt),
            "demo_time_scale": rt.demo_time_scale,
            "fast_forward": rt.env.fast_forward,
            "nature": rt.env.nature(),
            "nodes": node_views(rt),
            "zone_scenarios": zone_scenarios(rt),
            "recording": rt.recorder.status(),
            "replay": replay_view(ctx, rt),
        }


def sim_status(ctx: SimContext) -> dict[str, Any]:
    """The K2 ``sim.status`` data: runtime, broker connection, recording, replay and scenario-run state."""
    rt = ctx.runtime
    base = {
        "runtime": "running" if rt is not None and rt.started else "starting",
        "last_error": ctx.last_error,
        "broker_connected": False,
        "demo_time_scale": ctx.settings.demo_time_scale == "on",
        "fast_forward": 1,
        "recording": None,
        "replay": None,
        "scenario_run": ctx.running_run(),
    }
    if rt is None or not rt.started:
        return base
    with rt.lock:
        return {
            **base,
            "broker_connected": broker_connected(rt),
            "demo_time_scale": rt.demo_time_scale,
            "fast_forward": rt.env.fast_forward,
            "recording": rt.recorder.status(),
            "replay": replay_view(ctx, rt),
        }


# ---- sessions ------------------------------------------------------------------------------------------
def sessions_dir(ctx: SimContext) -> Path:
    rt = ctx.runtime
    return rt.recorder.sessions_dir if rt is not None else DEFAULT_SESSIONS_DIR


def session_entry(path: Path, meta: dict[str, Any] | None) -> dict[str, Any] | None:
    header: dict[str, Any] = {}
    try:
        with path.open(encoding="utf-8") as fh:
            header = json.loads(fh.readline() or "{}")
    except (OSError, ValueError):
        return None
    if header.get("kind") != KIND:
        return None
    m = meta or {}
    return {
        "id": m.get("id") or path.stem,
        "name": m.get("name") or header.get("name"),
        "created_at": m.get("created_at") or header.get("created_at"),
        "seed": m.get("seed", header.get("seed")),
        "duration_s": m.get("duration_s"),
        "message_count": m.get("message_count"),
        "nodes": [n.get("node_id") for n in header.get("nodes") or []],
        "kind": m.get("kind", "recording"),
        "uploaded": bool(m.get("uploaded", False)),
        "upload_error": m.get("upload_error"),
        "local": True,
        "file": path.name,
    }


def list_sessions(ctx: SimContext) -> list[dict[str, Any]]:
    """Local session files (newest first) with their upload state; the one being recorded is left out."""
    d = sessions_dir(ctx)
    rt = ctx.runtime
    current = rt.recorder.current_path if rt is not None else None
    out = []
    for path in d.glob("*.jsonl") if d.is_dir() else []:
        if current is not None and path == current:
            continue
        meta = None
        side = sidecar_path(path)
        if side.is_file():
            try:
                meta = json.loads(side.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = None
        entry = session_entry(path, meta)
        if entry is not None:
            out.append(entry)
    out.sort(key=lambda e: (e["created_at"] or "", e["file"]), reverse=True)
    return out


def find_session(ctx: SimContext, session_id: str) -> Path:
    for e in list_sessions(ctx):
        if e["id"] == session_id:
            return sessions_dir(ctx) / e["file"]
    raise ApiError("not_found", 404, f"No session {session_id}.")


# ---- helpers -------------------------------------------------------------------------------------------
def require_node(rt: Runtime, node_id: str) -> Any:
    nr = rt.nodes.get(node_id)
    if nr is None:
        raise ApiError("not_found", 404, f"No simulated node {node_id}.")
    return nr


def resolve_zone(rt: Runtime, raw: str) -> str:
    label = _ZONE_PREFIX.sub("", raw)
    if label not in rt.zone_bounds:
        raise ApiError("not_found", 404, f"No zone {raw}.")
    return label


def check_parameter(nr: Any, parameter: str) -> None:
    keys = NODE_KEYS[nr.node.node_type]
    if parameter not in keys:
        raise ApiError(
            "validation_error",
            422,
            f"{nr.node_id} ({nr.node.node_type}) has no parameter {parameter}.",
            {"parameters": list(keys)},
        )


def gs_answer(exc: GsError) -> JSONResponse:
    """Pass a Ground Station error through unchanged; an unreachable Ground Station is 503."""
    if exc.status is not None and isinstance(exc.body, dict):
        return JSONResponse(exc.body, status_code=exc.status)
    if exc.status is not None:
        return JSONResponse(
            envelope("upstream_error", f"The Ground Station answered HTTP {exc.status}."),
            status_code=exc.status,
        )
    return JSONResponse(envelope("upstream_unavailable", str(exc)), status_code=503)


async def json_object(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise ApiError("validation_error", 422, "The body must be a JSON object.")
    return body


async def reload_registry(rt: Runtime) -> None:
    try:
        await asyncio.to_thread(rt.on_registry_change)
    except Exception as exc:  # noqa: BLE001 - the Ground Station change is done; the watcher retries
        log.warning("registry reload after a lifecycle change failed: %s", exc)


def gs_method(rt: Runtime, name: str) -> Callable[..., Any]:
    fn = getattr(rt.gs, name, None)
    if fn is None:
        raise ApiError("not_implemented", 501, "This Ground Station client has no lifecycle routes.")
    return fn


# ---- routes --------------------------------------------------------------------------------------------
router = APIRouter(prefix="/api/v1")


@router.get("/state", summary="Simulator state (K1)")
async def get_state(request: Request) -> dict[str, Any]:
    return await asyncio.to_thread(full_state, ctx_of(request))


@router.get("/scenarios", summary="Scenario catalogue with default offsets")
async def get_scenarios() -> list[dict[str, Any]]:
    return [scenario_view(sid, d) for sid, d in SCENARIOS.items()]


@router.post("/zones/{zone_label}/scenario", summary="Apply a zone scenario (A1 reach)")
async def apply_scenario(request: Request, zone_label: str, body: ScenarioBody) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))
    if body.scenario not in SCENARIOS:
        raise ApiError(
            "validation_error", 422, f"Unknown scenario {body.scenario}.", {"scenarios": list(SCENARIOS)}
        )

    def apply() -> dict[str, Any]:
        label = resolve_zone(rt, zone_label)
        rt.scenarios.apply(label, body.scenario, body.ramp_s)
        active = rt.scenarios.active().get(label)
        if active is None:  # healthy (or recovery with nothing to recover from): the zone is clear
            keys: set[str] = set()
        elif active.scenario == "recovery":
            keys = set(active.frozen) | ({"do_mg_l"} if active.frozen_fraction else set())
        else:
            keys = scenario_keys(SCENARIOS[active.scenario])
        bounds = rt.zone_bounds[label]
        reached = []
        for nr in sorted(rt.nodes.values(), key=lambda n: n.node_id):
            n = nr.node
            if not keys & set(NODE_KEYS[n.node_type]):
                continue  # the scenario does not change this node's readings (e.g. the TG for sediment)
            f = reach_factor(n.node_type, n.e_m, n.s_m, bounds)
            if f > 0:
                reached.append({"node_id": nr.node_id, "factor": round(f, 3)})
        return {
            "zone_label": label,
            "scenario": active.scenario if active else None,
            "ramp_s": active.ramp_s if active else None,
            "nodes": reached,
            "warning": None if reached or not keys else f"no node in range of {label}",
        }

    return await locked(rt, apply)


@router.delete("/zones/{zone_label}/scenario", summary="Clear a zone scenario immediately")
async def clear_scenario(request: Request, zone_label: str) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))

    def clear() -> dict[str, Any]:
        label = resolve_zone(rt, zone_label)
        rt.scenarios.clear(label)
        return {"zone_label": label, "scenario": None}

    return await locked(rt, clear)


@router.post("/nodes/{node_id}/overrides", summary="Slider override (hold or drift)")
async def set_override(request: Request, node_id: str, body: OverrideBody) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))

    def apply() -> dict[str, Any]:
        nr = require_node(rt, node_id)
        check_parameter(nr, body.parameter)
        lo, hi, _res = RANGES[body.parameter]
        if not lo <= body.value <= hi:
            raise ApiError(
                "validation_error",
                422,
                f"{body.parameter} must be within {lo}..{hi}.",
                {"min": lo, "max": hi},
            )
        rt.overrides.set(node_id, body.parameter, body.value, body.behaviour)
        return node_view(rt, node_id)

    return await locked(rt, apply)


@router.delete("/nodes/{node_id}/overrides/{parameter}", summary="Remove an override")
async def clear_override(request: Request, node_id: str, parameter: str) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))

    def clear() -> dict[str, Any]:
        require_node(rt, node_id)
        rt.overrides.clear(node_id, parameter)
        return node_view(rt, node_id)

    return await locked(rt, clear)


@router.post("/nodes/{node_id}/health", summary="Battery and RSSI sliders")
async def set_health(request: Request, node_id: str, body: HealthBody) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))

    def apply() -> dict[str, Any]:
        nr = require_node(rt, node_id)
        if body.battery_pct is not None:
            nr.node.battery.set(body.battery_pct)
        if body.rssi_dbm is not None:
            nr.node.rssi_dbm = float(body.rssi_dbm)
        return node_view(rt, node_id)

    return await locked(rt, apply)


@router.post("/nodes/{node_id}/faults", summary="Inject a fault (F5)")
async def inject_fault(request: Request, node_id: str, body: FaultBody) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))
    if body.kind not in FAULT_KINDS:
        raise ApiError("validation_error", 422, f"Unknown fault {body.kind}.", {"kinds": sorted(FAULT_KINDS)})

    def apply() -> dict[str, Any]:
        nr = require_node(rt, node_id)
        params = dict(body.params or {})
        if body.kind in FAULT_PARAMETER_KINDS and "parameter" in params:
            check_parameter(nr, str(params["parameter"]))
        rt.faults(node_id).inject(body.kind, params)
        return node_view(rt, node_id)

    return await locked(rt, apply)


@router.delete("/nodes/{node_id}/faults/{kind}", summary="Clear a fault")
async def clear_fault(request: Request, node_id: str, kind: str) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))
    if kind not in FAULT_KINDS:
        raise ApiError("validation_error", 422, f"Unknown fault {kind}.", {"kinds": sorted(FAULT_KINDS)})

    def clear() -> dict[str, Any]:
        require_node(rt, node_id)
        rt.faults(node_id).clear(kind)
        return node_view(rt, node_id)

    return await locked(rt, clear)


@router.patch("/nature", summary="Natural behaviour: tide, diurnal cycles, noise, fast-forward")
async def patch_nature(request: Request, body: NatureBody) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))

    def apply() -> dict[str, Any]:
        env = rt.env
        if body.tide is not None:
            t = body.tide
            env.set_tide(t.mean_cm, t.amplitude_cm, t.spring_neap)
            env.set_nature(tide=t.enabled)
        env.set_nature(diurnal=body.diurnal, noise=body.noise)
        if body.fast_forward is not None:
            env.set_fast_forward(body.fast_forward)
        return {"nature": env.nature(), "fast_forward": env.fast_forward}

    return await locked(rt, apply)


# -- lifecycle (delegated to the Ground Station) -----------------------------------------------------------
@router.post("/lifecycle/install", summary="Install a node (delegated to the Ground Station's POST /nodes)")
async def lifecycle_install(request: Request) -> Any:
    rt = need_runtime(ctx_of(request))
    body = {**(await json_object(request)), "source": "simulated"}
    create = gs_method(rt, "create_node")
    try:
        if "node_type" not in body and isinstance(body.get("suggestion_id"), str):
            gaps = (await asyncio.to_thread(gs_method(rt, "coverage"))).get("gaps") or []
            gap = next((g for g in gaps if g.get("id") == body["suggestion_id"]), None)
            if gap is not None:  # else the Ground Station answers (404 for an unknown suggestion)
                body["node_type"] = gap["node_type"]
        result = await asyncio.to_thread(create, body)
    except GsError as exc:
        return gs_answer(exc)
    await reload_registry(rt)
    return result


@router.post("/lifecycle/{node_id}/move", summary="Move a node (delegated)")
async def lifecycle_move(request: Request, node_id: str) -> Any:
    rt = need_runtime(ctx_of(request))
    body = await json_object(request)
    try:
        result = await asyncio.to_thread(gs_method(rt, "move_node"), node_id, body)
    except GsError as exc:
        return gs_answer(exc)
    await reload_registry(rt)
    return result


@router.post("/lifecycle/{node_id}/remove", summary="Remove a node (delegated to decommission)")
async def lifecycle_remove(request: Request, node_id: str) -> Any:
    rt = need_runtime(ctx_of(request))
    body = await json_object(request)
    try:
        result = await asyncio.to_thread(gs_method(rt, "decommission_node"), node_id, body)
    except GsError as exc:
        return gs_answer(exc)
    await reload_registry(rt)
    return result


# -- recording, sessions and replay ------------------------------------------------------------------------
def meta_view(meta: Any) -> dict[str, Any]:
    d = meta.to_dict()
    return {
        **{k: d[k] for k in ("id", "name", "created_at", "seed", "duration_s", "message_count", "kind")},
        "nodes": [n.get("node_id") for n in d.get("nodes") or []],
        "uploaded": d["uploaded"],
        "upload_error": d["upload_error"],
        "local": True,
        "file": Path(d["path"]).name,
    }


@router.post("/recording/start", summary="Start recording outgoing messages")
async def recording_start(request: Request, body: RecordingBody) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))
    try:
        await asyncio.to_thread(rt.recorder.start, body.name)
    except RuntimeError as exc:
        raise ApiError("conflict", 409, str(exc)) from None
    status = rt.recorder.status()
    assert status is not None
    return status


@router.post("/recording/stop", summary="Stop recording; the session is uploaded through the Ground Station")
async def recording_stop(request: Request) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))
    try:
        meta = await asyncio.to_thread(rt.recorder.stop)
    except RuntimeError as exc:
        raise ApiError("conflict", 409, str(exc)) from None
    return meta_view(meta)


@router.get("/sessions", summary="Local sessions and their upload state")
async def get_sessions(request: Request) -> list[dict[str, Any]]:
    return await asyncio.to_thread(list_sessions, ctx_of(request))


@router.post("/sessions/{session_id}/replay", summary="Replay a session (always SIMULATED, replay = true)")
async def replay_session(request: Request, session_id: str) -> dict[str, Any]:
    ctx = ctx_of(request)
    rt = need_runtime(ctx)
    path = await asyncio.to_thread(find_session, ctx, session_id)
    try:
        await asyncio.to_thread(rt.replayer.replay, path)
    except (OSError, ValueError, KeyError) as exc:
        raise ApiError("validation_error", 422, f"Session {session_id} cannot be replayed: {exc}") from None
    ctx.replay_session[str(path)] = session_id
    return {"replay": replay_view(ctx, rt)}


@router.post("/replay/stop", summary="Stop the replay")
async def replay_stop(request: Request) -> dict[str, Any]:
    rt = need_runtime(ctx_of(request))
    await asyncio.to_thread(rt.replayer.stop)
    return {"replay": None}


# -- scenario runs ---------------------------------------------------------------------------------------
def script_text(body: ScenarioRunBody) -> str:
    if (body.script is None) == (body.name is None):
        raise ApiError("validation_error", 422, "Send exactly one of script (YAML text) or name.")
    if body.script is not None:
        return body.script
    name = str(body.name).removesuffix(".yaml").removesuffix(".yml")
    if not _SCRIPT_NAME.match(name):
        raise ApiError(
            "validation_error", 422, "name must be a script file name in services/simulator/scenarios/."
        )
    for suffix in (".yaml", ".yml"):
        path = SCENARIOS_DIR / f"{name}{suffix}"
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise ApiError("not_found", 404, f"No scenario script {name}.")


@router.post("/scenario-runs", status_code=202, summary="Run a timed scenario script on the live simulator")
async def start_scenario_run(request: Request, body: ScenarioRunBody) -> dict[str, Any]:
    ctx = ctx_of(request)
    rt = need_runtime(ctx)
    text = await asyncio.to_thread(script_text, body)
    try:
        script = load_script(text)
    except ScriptError as exc:
        raise ApiError("validation_error", 422, exc.message, {"line": exc.line}) from None
    requested = body.seed if body.seed is not None else script.seed
    note = None
    if requested != rt.seed:
        note = (
            f"the live simulator runs with seed {rt.seed}; a script seed applies to headless runs "
            "(bcs-sim scenario)"
        )
    run = ScenarioRun(
        uuid.uuid4().hex[:12], script.name, rt.seed, requested, to_iso(rt.clock.now()), note=note
    )
    with ctx.lock:
        busy = next((r.run_id for r in ctx.runs.values() if r.status == "running"), None)
        if busy is not None:
            raise ApiError("conflict", 409, f"Scenario run {busy} is still running.", {"run_id": busy})
        ctx.runs[run.run_id] = run

    def work() -> None:
        try:
            out = run_script(script, rt, rt.clock, realtime=True)
            run.log, run.status = out.to_dict(), "finished"
        except Exception as exc:
            log.exception("scenario run %s failed", run.run_id)
            run.error, run.status = f"{type(exc).__name__}: {exc}"[:300], "failed"
        finally:
            run.finished_at = to_iso(rt.clock.now())

    threading.Thread(target=work, name=f"bcs-sim-run-{run.run_id}", daemon=True).start()
    return run.view()


@router.get("/scenario-runs/{run_id}", summary="Scenario run status and log")
async def get_scenario_run(request: Request, run_id: str) -> dict[str, Any]:
    ctx = ctx_of(request)
    with ctx.lock:
        run = ctx.runs.get(run_id)
    if run is None:
        raise ApiError("not_found", 404, f"No scenario run {run_id}.")
    return run.view()
