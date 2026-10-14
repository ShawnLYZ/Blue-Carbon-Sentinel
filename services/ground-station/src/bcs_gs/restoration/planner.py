"""PlanService (product spec section 20): restoration plans with versions, catalogue checks and apply.

* ``propose(zone_ids)`` returns a request ID at once; it doubles as the new plan's ID. In the background
  the RestorationPlanner runs through the AIGateway at OPERATOR priority (its rules answer if the gateway
  call fails), its items pass the catalogue with invalid planting dropped (warnings), and version 1 is
  stored (source ``ai``, status ``draft``) and announced with ``plan.updated``.
* ``update(plan_id, items)`` checks the items against the catalogue (422 and nothing stored on a
  violation, so the plan stays editable) and stores version max + 1 as a draft: source ``operator``
  after an operator version, ``mixed`` after an AI or mixed one.
* ``apply(plan_id, version)`` (default: the latest version) starts the forecast first (its 409 leaves
  everything unchanged), marks the version ``applied`` (``applied_at`` kept on a re-apply), supersedes the
  plan's other applied version, records ``capture_at_application_id`` (the forecast's base: the latest
  evidence-grade capture, retention reason ``plan_application``, H7) and the forecast ID, asks the
  TreeService to locate trees (its failure never fails apply) and emits ``plan.updated``.

Zone state for the catalogue: mud and water from the latest evidence-grade capture's zone metrics,
porewater from the covering nodes' readings (as the risk engine fuses them), and the eroded edge from
the latest ready forecast's ``without`` land series (``catalogue.is_eroded``).

Warnings (species switches, dropped AI planting) are returned with the version that produced them and
kept in memory by version ID; they are not stored (the table has no column for them).
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

from bcs_protocol.timefmt import to_iso

from bcs_gs.ai.roles._common import RoleConfig
from bcs_gs.ai.roles.base import Priority
from bcs_gs.ai.roles.restoration_planner import PlannerInput, PlannerZone, RestorationPlanner
from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.core.aio import cancel_and_wait, to_thread_settled
from bcs_gs.core.ids import uuid7
from bcs_gs.history.service import source_chip
from bcs_gs.restoration.catalogue import ZonePlanState, is_eroded, validate_items

log = logging.getLogger("bcs_gs.plans")

TABLE = "restoration_plans"


class PlanService:
    def __init__(
        self, *, repo: Any, bus: Any, clock: Any, settings: Any, site: Any, captures: Any, fusion: Any,
        gateway: Any, forecasts: Any, trees: Any,
    ) -> None:  # fmt: skip
        self._repo, self._bus, self._clock, self._site = repo, bus, clock, site
        self._captures, self._fusion, self._gateway = captures, fusion, gateway
        self._forecasts, self._trees = forecasts, trees
        self._role = RestorationPlanner(RoleConfig.from_settings(settings))
        self._lock = asyncio.Lock()  # version numbers and apply are serialised
        self._warnings: dict[str, list[str]] = {}  # version row ID -> warnings when it was made
        self._bg: set[asyncio.Task[Any]] = set()

    # ---- lifecycle ----------------------------------------------------------------------------------
    async def stop(self) -> None:
        await self.cancel()

    async def cancel(self) -> None:
        """Cancel the proposals (and tree locations) in progress and wait until they ended (shutdown, test
        reset; ruling R30): a cancelled proposal stores no draft and publishes nothing."""
        await cancel_and_wait(list(self._bg))
        self._bg.clear()

    def reset(self) -> None:
        self._warnings.clear()

    def _spawn(self, coro: Any, name: str) -> None:
        t = asyncio.create_task(coro, name=name)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    # ---- zone context (blocking) --------------------------------------------------------------------
    def _zone_ids(self, wanted: list[str] | None) -> list[str]:
        known = [z.id for z in self._site.zones()]
        if wanted is None:
            return known
        unknown = sorted(set(wanted) - set(known))
        if unknown:
            raise ApiError("validation_error", 422, f"Unknown zone(s): {', '.join(unknown)}.")
        return list(dict.fromkeys(wanted))

    def _context(self, zone_ids: list[str]) -> dict[str, SimpleNamespace]:
        """Per zone: metrics (latest evidence-grade capture, or None), sensor readings, covered, eroded."""
        cap = self._forecasts.latest_evidence_capture()
        full = self._captures.get(cap["id"]) if cap is not None else None
        metrics = {zm.zone_id: zm for zm in full.zone_metrics} if full is not None else {}
        sensors = self._fusion.zone_sensors(zone_ids) if self._fusion is not None else {}
        land: dict[str, list[float]] = {}
        try:
            f = self._forecasts.latest()
            land = {
                z: [p.land.central for p in pts if p.year <= 2035]
                for z, pts in f.scenarios.without.zones.items()
            }
        except ApiError:
            pass  # no ready forecast yet: the eroded edge comes from water next to mud alone
        out = {}
        for z in zone_ids:
            zm = metrics.get(z)
            mud = zm.mud_pct / 100 if zm else 0.0
            water = zm.water_pct / 100 if zm else 0.0
            readings, covered = sensors.get(z, ({}, False))
            out[z] = SimpleNamespace(
                metrics=zm, readings=readings, covered=covered, mud=mud,
                eroded=is_eroded(water, mud, land.get(z)),
            )  # fmt: skip
        return out

    def zone_states(self) -> dict[str, ZonePlanState]:
        """The catalogue state of every zone. Blocking."""
        ctx = self._context(self._zone_ids(None))
        return {
            z: ZonePlanState(mud=c.mud, porewater_psu=c.readings.get("porewater_salinity"), eroded=c.eroded)
            for z, c in ctx.items()
        }

    def _planner_input(self, zone_ids: list[str]) -> PlannerInput:
        ctx = self._context(zone_ids)
        zones = []
        for z, c in ctx.items():
            found = self._fusion.list_assessments(z, 1) if self._fusion is not None else []
            a = found[0] if found else None
            zm = c.metrics
            fractions = (
                {"canopy": zm.canopy_pct / 100, "water": zm.water_pct / 100, "mud": zm.mud_pct / 100,
                 "other": zm.other_pct / 100}
                if zm else {}
            )  # fmt: skip
            zones.append(
                PlannerZone(
                    zone_id=z,
                    risk_class=a.risk_class if a else "low",
                    stressors={k: v for k, v in a.stressors.items() if v is not None} if a else {},
                    class_fractions=fractions,
                    porewater_psu=c.readings.get("porewater_salinity"),
                    covered=c.covered,
                )
            )
        return PlannerInput(zones=zones)

    # ---- propose ------------------------------------------------------------------------------------
    async def propose(self, zone_ids: list[str] | None) -> str:
        """Draft a plan in the background; returns the request ID, which is also the plan ID."""
        inp = await asyncio.to_thread(lambda: self._planner_input(self._zone_ids(zone_ids)))
        plan_id = uuid7()
        self._spawn(self._draft(plan_id, inp), f"plan-propose-{plan_id}")
        return plan_id

    async def _draft(self, plan_id: str, inp: PlannerInput) -> None:
        try:
            try:
                res = await self._gateway.call(self._role, inp, Priority.OPERATOR)
                out, call_id = res.output, res.source.ai_call_id
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("restoration planner call failed, using its rules: %r", exc)
                out, call_id = self._role.rules(inp), None
            states = await to_thread_settled(self.zone_states)
            items, warnings = validate_items(out.items, states, drop_invalid=True)
            row = {
                "id": uuid7(), "plan_id": plan_id, "version": 1, "created_at": to_iso(self._clock.now()),
                "source": "ai", "status": "draft", "items": [i.model_dump(mode="json") for i in items],
                "applied_at": None, "capture_at_application_id": None, "forecast_id": None, "ai_call_id": call_id,
            }  # fmt: skip
            async with self._lock:
                await to_thread_settled(self._repo.insert, TABLE, row)
            self._warnings[row["id"]] = warnings
            self._publish(row)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("restoration plan proposal %s failed", plan_id)

    # ---- update -------------------------------------------------------------------------------------
    async def update(self, plan_id: str, items: list[m.PlanItem]) -> m.PlanVersion:
        await asyncio.to_thread(self._row, plan_id, None)  # 404 first
        known = {z.id for z in self._site.zones()}
        unknown = sorted({i.zone_id for i in items} - known)
        if unknown:
            raise ApiError("validation_error", 422, f"Unknown zone(s): {', '.join(unknown)}.")
        states = await asyncio.to_thread(self.zone_states)
        norm, warnings = validate_items(items, states)  # 422 on a violation: nothing is stored
        async with self._lock:
            row = await asyncio.to_thread(self._insert_next, plan_id, norm)
        self._warnings[row["id"]] = warnings
        self._publish(row)
        return self._to_model(row)

    def _insert_next(self, plan_id: str, items: list[m.PlanItem]) -> dict[str, Any]:
        prev = self._row(plan_id, None)
        row = {
            "id": uuid7(), "plan_id": plan_id, "version": prev["version"] + 1,
            "created_at": to_iso(self._clock.now()),
            "source": "operator" if prev["source"] == "operator" else "mixed", "status": "draft",
            "items": [i.model_dump(mode="json") for i in items], "applied_at": None,
            "capture_at_application_id": None, "forecast_id": None, "ai_call_id": None,
        }  # fmt: skip
        self._repo.insert(TABLE, row)
        return row

    # ---- apply --------------------------------------------------------------------------------------
    async def apply(self, plan_id: str, version: int | None) -> tuple[m.PlanVersion, str]:
        async with self._lock:
            row = await asyncio.to_thread(self._row, plan_id, version)
            forecast_id = await self._forecasts.start(row["id"])  # 409 here changes nothing
            row = await asyncio.to_thread(self._mark_applied, row["id"], forecast_id)
        self._spawn(self._locate(), f"plan-locate-{plan_id}")
        self._publish(row)
        return self._to_model(row), forecast_id

    def _mark_applied(self, version_id: str, forecast_id: str) -> dict[str, Any]:
        row = self._repo.get(TABLE, {"id": version_id})
        forecast = self._repo.get("forecasts", {"id": forecast_id})
        capture_id = forecast["base_capture_id"]  # the latest evidence-grade capture
        applied = self._repo.query(
            f"SELECT * FROM {TABLE} WHERE plan_id = ? AND status = 'applied' AND id != ?",
            (row["plan_id"], version_id), table=TABLE,
        )  # fmt: skip
        row = {
            **row, "status": "applied",
            "applied_at": row["applied_at"] if row["status"] == "applied" else to_iso(self._clock.now()),
            "capture_at_application_id": capture_id, "forecast_id": forecast_id,
        }  # fmt: skip
        with self._repo.transaction():
            for old in applied:
                self._repo.upsert(TABLE, {**old, "status": "superseded"})
            self._repo.upsert(TABLE, row)
        self._captures.mark_referenced(capture_id, "plan_application")  # H7
        return row

    async def _locate(self) -> None:
        """Tree location on plan application; a failure (e.g. no class map yet) is only logged."""
        try:
            await self._trees.locate(None, Priority.OPERATOR)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.info("tree location on plan application skipped: %s", exc)

    # ---- read ---------------------------------------------------------------------------------------
    def _row(self, plan_id: str, version: int | None) -> dict[str, Any]:
        """The version row (default: the latest) or 404. Blocking."""
        if version is None:
            rows = self._repo.query(
                f"SELECT * FROM {TABLE} WHERE plan_id = ? ORDER BY version DESC LIMIT 1",
                (plan_id,),
                table=TABLE,
            )
        else:
            rows = self._repo.query(
                f"SELECT * FROM {TABLE} WHERE plan_id = ? AND version = ?", (plan_id, version), table=TABLE
            )
        if not rows:
            what = f"plan {plan_id}" if version is None else f"version {version} of plan {plan_id}"
            raise ApiError("not_found", 404, f"No {what}.")
        return rows[0]

    def get(self, plan_id: str, version: int | None = None) -> m.PlanVersion:
        return self._to_model(self._row(plan_id, version))

    def list(self) -> list[m.PlanSummary]:
        """The latest version of each plan, newest first. Blocking."""
        rows = self._repo.query(
            f"SELECT * FROM {TABLE} r WHERE version = "
            f"(SELECT MAX(version) FROM {TABLE} WHERE plan_id = r.plan_id) ORDER BY created_at DESC, id DESC",
            table=TABLE,
        )
        return [self._summary(r) for r in rows]

    def _summary(self, r: dict[str, Any]) -> m.PlanSummary:
        return m.PlanSummary(
            plan_id=r["plan_id"], version=r["version"], status=r["status"], source=r["source"],
            created_at=r["created_at"], applied_at=r["applied_at"],
            zones=sorted({i["zone_id"] for i in r["items"] or []}),
        )  # fmt: skip

    def _to_model(self, r: dict[str, Any]) -> m.PlanVersion:
        if r["ai_call_id"]:
            chip = source_chip(self._repo, r["ai_call_id"])
        else:
            chip = m.SourceChip(tier="rules", cached=False) if r["source"] == "ai" else None
        return m.PlanVersion(
            id=r["id"], plan_id=r["plan_id"], version=r["version"], created_at=r["created_at"],
            source=r["source"], status=r["status"],
            items=[m.PlanItem.model_validate(i) for i in r["items"] or []],
            applied_at=r["applied_at"], capture_at_application_id=r["capture_at_application_id"],
            forecast_id=r["forecast_id"], ai=chip, warnings=list(self._warnings.get(r["id"], [])),
        )  # fmt: skip

    def _publish(self, row: dict[str, Any]) -> None:
        self._bus.publish("plan.updated", self._summary(row).model_dump(mode="json"))
