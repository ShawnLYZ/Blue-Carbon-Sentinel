"""ForecastService (spec section 19): 2026-2035 forecasts from the latest evidence-grade capture.

``start(plan_version_id)`` checks the inputs (409 without an evidence-grade capture or a baseline), stores
a ``pending`` row, marks the base capture referenced (A2, H7) and runs the forecast in the background:

* **State.** Per zone, from the capture's metrics, the baseline's VARI and the zone's latest assessment;
  ``water_adjacent`` is water >= 5 % in the zone or a 4-neighbour (ruling R2).
* **Parameters.** One ForecastParameterEstimator call per zone through the AIGateway at OPERATOR priority.
  The cache key is the SHA-256 of (zone state and stressors quantised to fixed steps, the zone's plan
  items; ruling R27): C, H and L to 0.02, sigma and each stressor score to 0.05. A zone whose inputs did
  not change by about half a step reuses its parameters (in memory, else from a stored forecast) and its chip
  says ``cached``. Operator calls skip the gateway's own cache read, hence this one. Every tier is cached,
  but gemma_local / rules answers expire after 10 minutes on the service clock (ruling R17). A run makes at
  most 4 fresh gateway calls within an 18 s deadline; other zones get the rules answer (rulings R16, R26).
* **Result.** The pure engine runs; the row gets parameters, source chips, keyframes (with sigma and
  cohort fraction, ruling R6), summary (``elapsed_ms``, ``confidence_prediction``), bands and input hash.
  ``confidence_prediction`` is N4: min over zones of tier factor x narrowness, narrowness =
  1 - 0.5 x mean over parameters of |high - low| / (bound high - bound low).
* ``forecast.ready {forecast_id, plan_id, status}`` (J2) ends every run, ``failed`` ones included. A run
  cancelled at shutdown is marked ``failed``; ``pending`` rows found at construction are marked ``failed``.
* ``latest()`` is the newest ``ready`` forecast (ruling R18).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from bcs_protocol.timefmt import from_iso, to_iso

from bcs_gs.ai.cache import canonical_json, sha256_hex
from bcs_gs.ai.roles._common import RoleConfig
from bcs_gs.ai.roles.base import Priority
from bcs_gs.ai.roles.forecast_parameter_estimator import (
    PARAM_KEYS,
    ForecastParameterEstimator,
    FpeInput,
    bounds,
)
from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.core.aio import cancel_and_wait, to_thread_settled
from bcs_gs.core.ids import uuid7
from bcs_gs.forecast.engine import ForecastResult, run_forecast
from bcs_gs.forecast.state import ZoneState, initial_state

log = logging.getLogger("bcs_gs.forecast")

WATER_ADJACENT_PCT = 5.0
MAX_FRESH_CALLS = 4  # ruling R16: fresh gateway (cloud-tier) calls per run; further zones use rules
PARAM_DEADLINE_S = 18.0  # rulings R16, R26: per-run parameter deadline (spec <= 20 s); late zones use rules
STATE_STEP = 0.02  # ruling R27: cache-key step of C, H and L
SCORE_STEP = 0.05  # ruling R27: cache-key step of sigma and each stressor score
DEGRADED_TTL = timedelta(minutes=10)  # ruling R17: gemma_local / rules cache entries expire
DEGRADED_PROVIDERS = frozenset({"ollama", "rules"})
PERSISTED_LOOKBACK = 5  # stored forecasts searched for a cached zone's parameters
DEFAULT_FACTOR = 0.75  # the rules tier's factor, for a tier without one


@dataclasses.dataclass(frozen=True)
class _Params:
    bands: dict[str, dict[str, float]]
    tier: str
    model: str | None
    ai_call_id: str | None
    at: datetime  # when the answer was produced (service clock)


@dataclasses.dataclass
class _Inputs:
    capture_id: str
    states: dict[str, ZoneState]
    plan_row: dict[str, Any] | None
    plan: Any | None  # object with ``items`` (PlanItem list) for the engine


def _r3(v: float) -> float:
    return round(float(v), 3)


def quantise(v: float, step: float) -> str:
    """``v`` rounded to the nearest multiple of ``step``, as a fixed-point string (deterministic; no
    float noise such as 0.30000000000000004). Halves round to even."""
    n = round(float(v) / step)
    return f"{n * step:.2f}"


def cache_key(state: ZoneState, items: list[m.PlanItem], role: Any) -> str:
    """SHA-256 of the zone state and stressors quantised to fixed steps (ruling R27) and its plan items."""
    doc = {
        "role": [role.name, role.schema_version, role.prompt_version],
        "state": {"C": quantise(state.C, STATE_STEP), "H": quantise(state.H, STATE_STEP),
                  "L": quantise(state.L, STATE_STEP), "sigma": quantise(state.sigma, SCORE_STEP),
                  "water_adjacent": state.water_adjacent},
        "stressors": {k: quantise(v, SCORE_STEP) for k, v in sorted(state.stressors.items())},
        "plan_items": [i.model_dump(mode="json") for i in items],
    }  # fmt: skip
    return sha256_hex(canonical_json(doc))


def water_adjacent(zones: list[Any], water_pct: dict[str, float]) -> dict[str, bool]:
    """Ruling R2: water >= 5 % in the zone or in a 4-neighbour."""
    at = {(z.col, z.row): z.id for z in zones}
    out = {}
    for z in zones:
        cells = [
            (z.col, z.row),
            (z.col - 1, z.row),
            (z.col + 1, z.row),
            (z.col, z.row - 1),
            (z.col, z.row + 1),
        ]
        out[z.id] = any(water_pct.get(at.get(c, ""), 0.0) >= WATER_ADJACENT_PCT for c in cells)
    return out


def narrowness(bands: dict[str, Any], allowed: dict[str, tuple[float, float]]) -> float:
    widths = []
    for key, (lo, hi) in allowed.items():
        b = bands.get(key)
        if b is None or hi <= lo:
            continue
        widths.append(abs(float(b["high"]) - float(b["low"])) / (hi - lo))
    return 1.0 - 0.5 * (sum(widths) / len(widths)) if widths else 1.0


def _failed(row: dict[str, Any], error: str) -> dict[str, Any]:
    return {**row, "status": "failed", "summary": {**(row.get("summary") or {}), "error": error[:300]}}


class ForecastService:
    def __init__(
        self, *, repo: Any, bus: Any, clock: Any, settings: Any, site: Any, captures: Any, fusion: Any,
        gateway: Any,
    ) -> None:  # fmt: skip
        self._repo, self._bus, self._clock, self._site = repo, bus, clock, site
        self._captures, self._fusion, self._gateway = captures, fusion, gateway
        self._settings = settings
        self._role = ForecastParameterEstimator(RoleConfig.from_settings(settings), settings.forecast)
        self._bounds = bounds(settings.forecast)
        self._cache: dict[str, _Params] = {}
        self._lock = asyncio.Lock()  # one run at a time: a second identical run reuses the first's params
        self._bg: set[asyncio.Task[Any]] = set()
        self._fail_stale_pending()

    # ---- lifecycle ----------------------------------------------------------------------------------
    async def stop(self) -> None:
        await self.cancel()

    async def cancel(self) -> None:
        """Cancel the runs in progress and wait until they ended (shutdown, test reset; ruling R30). A
        cancelled run marks its row ``failed`` and publishes nothing."""
        await cancel_and_wait(list(self._bg))
        self._bg.clear()

    def reset(self) -> None:
        self._cache.clear()

    def _fail_stale_pending(self) -> None:
        """A run is never resumed: ``pending`` rows left by an earlier process (e.g. one stopped mid-run)
        are marked ``failed``. Runs at construction, before any run of this instance."""
        rows = self._repo.query("SELECT * FROM forecasts WHERE status = 'pending'", table="forecasts")
        for r in rows:
            self._repo.upsert(
                "forecasts", _failed(r, "interrupted: the Ground Station stopped during the run")
            )

    def _spawn(self, coro: Any, name: str) -> None:
        t = asyncio.create_task(coro, name=name)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    # ---- plans (ruling R9) --------------------------------------------------------------------------
    def resolve_plan(self, plan_id: str | None) -> str | None:
        """A plan's applied version, else its latest; without ``plan_id`` the latest applied plan, else
        none. Blocking."""
        q = self._repo.query
        if plan_id is None:
            rows = q(
                "SELECT id FROM restoration_plans WHERE status = 'applied' "
                "ORDER BY applied_at DESC, version DESC LIMIT 1",
                table="restoration_plans",
            )
            return rows[0]["id"] if rows else None
        rows = q(
            "SELECT id FROM restoration_plans WHERE plan_id = ? "
            "ORDER BY CASE status WHEN 'applied' THEN 0 ELSE 1 END, version DESC LIMIT 1",
            (plan_id,), table="restoration_plans",
        )  # fmt: skip
        if not rows:
            raise ApiError("not_found", 404, f"No plan {plan_id}.")
        return rows[0]["id"]

    # ---- start --------------------------------------------------------------------------------------
    async def start(self, plan_version_id: str | None) -> str:
        """Store a ``pending`` forecast and run it in the background; returns its ID."""
        capture_id, plan_id = await asyncio.to_thread(self._check, plan_version_id)
        fid = uuid7()
        row = {
            "id": fid, "created_at": to_iso(self._clock.now()), "status": "pending",
            "plan_version_id": plan_version_id, "base_capture_id": capture_id, "input_hash": "",
            "parameters": {}, "parameter_sources": {}, "keyframes": {}, "summary": {}, "bands": {},
        }  # fmt: skip

        def store() -> None:
            self._repo.insert("forecasts", row)
            self._captures.mark_referenced(capture_id)  # A2, H7

        await asyncio.to_thread(store)
        self._spawn(self._run(row, plan_id), f"forecast-{fid}")
        return fid

    def latest_evidence_capture(self) -> dict[str, Any] | None:
        """The latest evidence-grade capture row (the forecast base; a plan's capture at application).
        Blocking."""
        rows = self._repo.query(
            "SELECT * FROM captures WHERE evidence_grade = 1 ORDER BY taken_at DESC, id DESC LIMIT 1",
            table="captures",
        )
        return rows[0] if rows else None

    def _check(self, plan_version_id: str | None) -> tuple[str, str | None]:
        """(base capture ID, plan ID) or 409 / 404."""
        cap = self.latest_evidence_capture()
        if cap is None:
            raise ApiError("conflict", 409, "The forecast needs an evidence-grade capture; take one first.")
        if self._captures.baseline() is None:
            raise ApiError("conflict", 409, "The forecast needs a baseline; set one first.")
        if plan_version_id is None:
            return cap["id"], None
        plan = self._repo.get("restoration_plans", {"id": plan_version_id})
        if plan is None:
            raise ApiError("not_found", 404, f"No plan version {plan_version_id}.")
        return cap["id"], plan["plan_id"]

    # ---- the run ------------------------------------------------------------------------------------
    async def _run(self, row: dict[str, Any], plan_id: str | None) -> None:
        try:
            async with self._lock:
                t0 = time.perf_counter()
                inputs = await to_thread_settled(self._inputs, row["base_capture_id"], row["plan_version_id"])
                params, keys, fresh = await self._parameters(inputs)
                result = await to_thread_settled(
                    run_forecast,
                    inputs.states,
                    {z: p.bands for z, p in params.items()},
                    inputs.plan,
                    self._settings.carbon,
                )
                done = self._finish(row, inputs, params, keys, fresh, result, t0)
                await to_thread_settled(self._repo.upsert, "forecasts", done)
        except asyncio.CancelledError:
            # Shutdown: record the end synchronously (no await while cancelled); the database is still open.
            with contextlib.suppress(Exception):
                self._repo.upsert("forecasts", _failed(row, "cancelled: the Ground Station stopped"))
            raise
        except Exception as exc:
            log.exception("forecast %s failed", row["id"])
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    self._repo.upsert, "forecasts", _failed(row, f"{type(exc).__name__}: {exc}")
                )
            self._bus.publish(
                "forecast.ready", {"forecast_id": row["id"], "plan_id": plan_id, "status": "failed"}
            )
            return
        self._bus.publish("forecast.ready", {"forecast_id": row["id"], "plan_id": plan_id, "status": "ready"})

    def _inputs(self, capture_id: str, plan_version_id: str | None) -> _Inputs:
        cap = self._captures.get(capture_id)
        base = self._captures.baseline()
        if cap is None or base is None:
            raise RuntimeError("the base capture or the baseline disappeared")
        base_vari = {zm.zone_id: zm.vari_mean for zm in base.zone_metrics}
        metrics = {zm.zone_id: zm for zm in cap.zone_metrics}
        adjacent = water_adjacent(self._site.zones(), {z: zm.water_pct for z, zm in metrics.items()})
        states = {}
        for z, zm in metrics.items():
            found = self._fusion.list_assessments(z, 1) if self._fusion is not None else []
            states[z] = initial_state(
                zm, base_vari.get(z), found[0] if found else None, adjacent.get(z, False)
            )
        plan_row = self._repo.get("restoration_plans", {"id": plan_version_id}) if plan_version_id else None
        plan = None
        if plan_row is not None:
            plan = SimpleNamespace(items=[m.PlanItem.model_validate(i) for i in plan_row["items"] or []])
        return _Inputs(capture_id, states, plan_row, plan)

    async def _parameters(self, inputs: _Inputs) -> tuple[dict[str, _Params], dict[str, str], set[str]]:
        """(parameters per zone, cache key per zone, keys answered fresh in this run).

        Ruling R16: at most ``MAX_FRESH_CALLS`` gateway calls per run, all within ``PARAM_DEADLINE_S``;
        keys beyond the cap, past the deadline or whose call failed get the role's rules answer."""
        plan_items = inputs.plan.items if inputs.plan else []
        items = {z: [i for i in plan_items if i.zone_id == z] for z in inputs.states}
        keys = {z: cache_key(s, items[z], self._role) for z, s in inputs.states.items()}
        missing = {k for k in keys.values() if not self._usable(self._cache.get(k))}
        if missing:
            stored = await asyncio.to_thread(self._persisted, missing)
            self._cache.update({k: p for k, p in stored.items() if self._usable(p)})
        todo: dict[str, str] = {}  # one answer per distinct key: key -> a zone that has it
        for z in sorted(inputs.states):
            if not self._usable(self._cache.get(keys[z])):
                todo.setdefault(keys[z], z)

        def fpe_input(z: str) -> FpeInput:
            s = inputs.states[z]
            return FpeInput(
                zone_id=z,
                state={"C": _r3(s.C), "H": _r3(s.H), "L": _r3(s.L), "sigma": _r3(s.sigma)},
                stressors={k: _r3(v) for k, v in sorted(s.stressors.items())},
                plan_items=items[z],
                water_adjacent=s.water_adjacent,
            )

        def store(key: str, out: Any, tier: str, model: str | None, call_id: str | None) -> None:
            bands = {k: b.model_dump() for k, b in out.params.items() if k in PARAM_KEYS}
            self._cache[key] = _Params(bands, tier, model, call_id, self._clock.now())

        async def fetch(key: str, z: str) -> None:
            res = await self._gateway.call(self._role, fpe_input(z), Priority.OPERATOR)
            store(key, res.output, res.source.tier, res.source.model, res.source.ai_call_id)

        called = list(todo.items())[:MAX_FRESH_CALLS]
        tasks = [asyncio.create_task(fetch(k, z), name=f"forecast-fpe-{z}") for k, z in called]
        try:
            if tasks:
                _, late = await asyncio.wait(tasks, timeout=PARAM_DEADLINE_S)
                for t in late:
                    t.cancel()
                for t in tasks:
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await t
                for t in tasks:
                    if not t.cancelled() and t.exception() is not None:
                        log.warning("forecast parameters: %s failed: %r", t.get_name(), t.exception())
        finally:
            # The run itself was cancelled (shutdown, test reset) while waiting: no fetch outlives it.
            orphans = [t for t in tasks if not t.done()]
            for t in orphans:
                t.cancel()
            if orphans:
                await asyncio.wait(orphans)
        for k, z in todo.items():
            if not self._usable(self._cache.get(k)):  # beyond the cap, late or failed
                store(k, self._role.rules(fpe_input(z)), "rules", None, None)
        return {z: self._cache[keys[z]] for z in inputs.states}, keys, set(todo)

    def _usable(self, p: _Params | None) -> bool:
        """Ruling R17: every tier is cached; gemma_local / rules answers expire after 10 minutes."""
        if p is None:
            return False
        t = self._gateway.tiers.get(p.tier)
        provider = t.provider if t is not None else p.tier
        return provider not in DEGRADED_PROVIDERS or self._clock.now() - p.at <= DEGRADED_TTL

    def _persisted(self, wanted: set[str]) -> dict[str, _Params]:
        """Parameters of earlier stored forecasts whose zone cache key is wanted. Blocking."""
        found: dict[str, _Params] = {}
        rows = self._repo.query(
            "SELECT created_at, parameters, parameter_sources FROM forecasts WHERE status = 'ready' "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (PERSISTED_LOOKBACK,), table="forecasts",
        )  # fmt: skip
        for r in rows:
            for z, src in (r["parameter_sources"] or {}).items():
                k = src.get("cache_key")
                bands = (r["parameters"] or {}).get(z)
                if k in wanted and k not in found and bands:
                    at = from_iso(src.get("cached_at") or r["created_at"])
                    found[k] = _Params(bands, src["tier"], src.get("model"), src.get("ai_call_id"), at)
        return found

    def _factor(self, tier: str) -> float:
        t = self._gateway.tiers.get(tier)
        f = t.factor if t is not None else None
        return float(f) if f is not None else DEFAULT_FACTOR

    def zone_predictions(self, row: dict[str, Any]) -> dict[str, float]:
        """N4 prediction component per zone of a stored forecast row: the ForecastParameterEstimator's tier
        factor x narrowness of that zone's parameters (``confidence_prediction`` is their minimum). The
        ledger's per-zone confidence uses it (N4 "Ledger use")."""
        params = row.get("parameters") or {}
        return {
            z: self._factor(src["tier"]) * narrowness(params.get(z) or {}, self._bounds)
            for z, src in sorted((row.get("parameter_sources") or {}).items())
        }

    def _finish(
        self,
        row: dict[str, Any],
        inputs: _Inputs,
        params: dict[str, _Params],
        keys: dict[str, str],
        fresh: set[str],
        result: ForecastResult,
        t0: float,
    ) -> dict[str, Any]:
        sources = {
            z: {"tier": p.tier, "model": p.model, "cached": keys[z] not in fresh, "ai_call_id": p.ai_call_id,
                "cache_key": keys[z], "cached_at": to_iso(p.at)}
            for z, p in sorted(params.items())
        }  # fmt: skip
        conf = min(
            (self._factor(p.tier) * narrowness(p.bands, self._bounds) for p in params.values()), default=0.0
        )
        keyframes = {
            sc: {"site": [dataclasses.asdict(y) for y in series.site],
                 "zones": {z: [dataclasses.asdict(y) for y in pts] for z, pts in series.zones.items()}}
            for sc, series in result.scenarios.items()
        }  # fmt: skip
        plan = inputs.plan_row
        input_hash = sha256_hex(
            canonical_json(
                {
                    "capture_id": inputs.capture_id,
                    "states": {z: dataclasses.asdict(s) for z, s in sorted(inputs.states.items())},
                    "parameters": {z: p.bands for z, p in sorted(params.items())},
                    "plan_items": plan["items"] if plan else None,
                }
            )
        )
        summary = {
            "years": result.years,
            "plan_id": plan["plan_id"] if plan else None,
            "plan_version": plan["version"] if plan else None,
            "confidence_prediction": round(conf, 4),
            "zones": len(params),
            "fresh_parameter_calls": len(fresh),
            # The zones' starting stressors, kept with the forecast so a render reproduces from the row.
            "base_stressors": {z: {k: _r3(v) for k, v in sorted(s.stressors.items())}
                               for z, s in sorted(inputs.states.items())},
        }  # fmt: skip
        for sc, series in result.scenarios.items():
            if series.site:
                last = series.site[-1]
                summary[f"{sc}_{last.year}"] = {
                    "canopy": last.canopy.central, "stock_tco2e": last.stock_tco2e.central,
                    "additional_tco2e": last.additional_tco2e.central,
                }  # fmt: skip
        summary["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        bands = {
            "runs": ["low", "central", "high"],
            "ordering": "outcome: low pessimistic, high optimistic (rulings R1, R3)",
            "parameter_bounds": {k: list(v) for k, v in self._bounds.items()},
        }
        return {
            **row, "status": "ready", "input_hash": input_hash,
            "parameters": {z: p.bands for z, p in sorted(params.items())}, "parameter_sources": sources,
            "keyframes": keyframes, "summary": summary, "bands": bands,
        }  # fmt: skip

    # ---- read ---------------------------------------------------------------------------------------
    def latest(self) -> m.Forecast:
        """The newest ready forecast (ruling R18)."""
        rows = self._repo.query(
            "SELECT * FROM forecasts WHERE status = 'ready' ORDER BY created_at DESC, id DESC LIMIT 1",
            table="forecasts",
        )
        if not rows:
            raise ApiError("not_found", 404, "There is no ready forecast yet.")
        return self._to_model(rows[0])

    def get(self, forecast_id: str) -> m.Forecast:
        row = self._repo.get("forecasts", {"id": forecast_id})
        if row is None:
            raise ApiError("not_found", 404, f"No forecast {forecast_id}.")
        return self._to_model(row)

    def _to_model(self, r: dict[str, Any]) -> m.Forecast:
        plan = (
            self._repo.get("restoration_plans", {"id": r["plan_version_id"]})
            if r["plan_version_id"]
            else None
        )
        kf = r["keyframes"] or {}
        empty = {"site": [], "zones": {}}
        summary = dict(r["summary"] or {})
        return m.Forecast.model_validate(
            {
                "id": r["id"], "created_at": r["created_at"], "status": r["status"],
                "plan_id": plan["plan_id"] if plan else None, "plan_version": plan["version"] if plan else None,
                "base_capture_id": r["base_capture_id"], "years": summary.get("years", []),
                "scenarios": {"without": kf.get("without", empty), "with": kf.get("with", empty)},
                "parameter_sources": {
                    z: {k: v for k, v in s.items() if k in m.SourceChip.model_fields}
                    for z, s in (r["parameter_sources"] or {}).items()
                },
                "confidence_prediction": summary.get("confidence_prediction", 0.0),
                "summary": summary,
            }
        )  # fmt: skip
