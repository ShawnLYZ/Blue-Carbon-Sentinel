"""LedgerService (spec 23; addendum A5, H2 ``ledger_records``, H4, H7, I3, J2, N4, N13): the single writer of
the append-only, SHA-256 hash-chained carbon ledger.

* ``append(content)`` is the only writer. Under one ``asyncio.Lock`` it allocates the next ``chain_index``
  locally (so the chain stays valid offline), the ``BC-{yyyy}-{nnnnn}`` record ID from the per-UTC-year
  sequence, ``created_at`` and ``previous_hash``; serialises the content canonically (N13), hashes it and
  stores the row with ``Repo.insert`` (``insert_ignore`` sync, A5). The display columns are copies of the
  content's fields. The label and methodology wording are always the exact constants (a caller's values
  are overwritten). Captures named in the evidence are marked referenced with reason ``ledger_evidence``
  (protected, uploaded; H7, A2). Then ``ledger.appended`` and the ``ledger_issued`` alert.
* ``checklist(plan_id)``: satellite (an evidence-grade capture exists), sensor (every plan zone covered by
  a WQ or SP), ai (the plan's forecast is ready with stored parameters), restoration (the version is
  applied). The plan version is the applied one, else the latest.
* ``create_projected(plan_id)``: 422 with the checklist when incomplete; idempotent per plan version (the
  check runs under the append lock, so concurrent presses get the same record). Per zone, gross = the
  plan's additionality (``carbon.plan_additionality``) and confidence = N4 ledger confidence: the zone's
  camera and sensor components from its latest assessment with the forecast's prediction component for
  the zone (``ForecastService.zone_predictions``), combined by ``fusion.confidence.overall``. The record's
  confidence is the minimum over zones, and every zone's deductions use it; quantity = the sum of the zone
  nets.
* ``verify_chain()`` checks the whole chain (``ledger.chain.verify``: links, hashes and that every display
  column equals its canonical field), emits ``ledger.verified``; a failure
  raises ``chain_broken`` and sets ``issuance_blocked`` (Verified issuance stops; Task 4).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from bcs_protocol.timefmt import to_iso

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.capture.service import CaptureNotFound
from bcs_gs.core.ids import ledger_record_id
from bcs_gs.fusion.confidence import overall
from bcs_gs.ledger.canonical import GENESIS_PREV, canonical_json, fmt_frac, fmt_pct, fmt_tco2e, record_hash
from bcs_gs.ledger.chain import DISPLAY_COLUMNS, ChainVerification, StoredRecord, verify
from bcs_gs.ledger.contents import CANONICAL_BLOB, canonical_text, parse_canonical, stored_contents
from bcs_gs.nodes.coverage import by_zone
from bcs_gs.store.retention import evidence_capture_ids

log = logging.getLogger(__name__)
LABEL = "Demo record — not a certified carbon credit"
METHOD_NOTE = "aligned with Verra VM0033 (Tidal Wetland and Seagrass Restoration) concepts — demo, not certified"
TABLE = "ledger_records"
CHECKLIST_KEYS = ("satellite", "sensor", "ai", "restoration")
TELEMETRY_WINDOW_S = 600  # the sensor evidence of a Projected record: the last 10 minutes of samples
LATEST_CAPTURES = 3  # the latest evidence-grade captures cited
NO_COMPONENT = 0.1  # N4: camera with no capture, sensor with no covering node
COLUMNS = (
    "chain_index", "record_id", "type", "created_at", "site_id", "zone_ids", "period", "quantity_tco2e",
    "gross_tco2e", "deductions", "evidence", "confidence", "method_note", "label", "projected_record_id",
)  # fmt: skip
# a record as the API shows it: canonical read as a BLOB, so an undecodable row never fails the listing
SELECT_RECORD = (
    "SELECT chain_index, "
    + ", ".join(f"CAST({c} AS BLOB) AS {c}" for c in ("record_id", "type", "created_at", "quantity_tco2e"))
    + f", {CANONICAL_BLOB}, CAST(previous_hash AS BLOB) AS previous_hash, CAST(hash AS BLOB) AS hash"
)
REQUIRED = ("type", "site_id", "zone_ids", "period", "quantity_tco2e", "gross_tco2e", "deductions", "evidence",
            "confidence")  # fmt: skip


def _dec(x: float, places: int = 4) -> Decimal:
    return Decimal(str(round(float(x), places)))


def _stat(x: float) -> str:
    return fmt_frac(_dec(x))


class LedgerService:
    def __init__(
        self, repo: Any, bus: Any, alerts: Any, clock: Any, carbon: Any, *, settings: Any, forecasts: Any,
        captures: Any, registry: Any, grid: Any, site_id: str,
    ) -> None:  # fmt: skip
        self._repo, self._bus, self._alerts, self._clock, self._carbon = repo, bus, alerts, clock, carbon
        self._settings, self._forecasts = settings, forecasts
        self._captures, self._registry, self._grid, self._site_id = captures, registry, grid, site_id
        self._lock = asyncio.Lock()
        self._last: ChainVerification | None = None
        self.issuance_blocked = False

    def reset(self) -> None:
        self._last = None
        self.issuance_blocked = False

    # ---- read ---------------------------------------------------------------------------------------
    def records(self) -> list[m.LedgerRecord]:
        """Newest first (I1). Blocking."""
        rows = self._repo.query(f"{SELECT_RECORD} FROM {TABLE} ORDER BY chain_index DESC", table=TABLE)
        return [self._model(r) for r in rows]

    def get(self, record_id: str) -> m.LedgerRecord:
        rows = self._repo.query(f"{SELECT_RECORD} FROM {TABLE} WHERE record_id = ?", (record_id,), table=TABLE)
        if not rows:
            raise ApiError("not_found", 404, f"No ledger record {record_id}.")
        return self._model(rows[0])

    def _link_ok(self, chain_index: int) -> bool | None:
        v = self._last
        if v is None:
            return None
        if v.intact:
            return True if chain_index < v.checked else None
        assert v.first_broken_index is not None
        return chain_index < v.first_broken_index

    def _model(self, r: dict[str, Any]) -> m.LedgerRecord:
        """The fields come from the hashed canonical content; a display column is used only when the
        canonical text cannot be read at all (the chain then reports that record broken)."""
        parsed = parse_canonical(r["canonical"])
        content = parsed or {}

        def field(key: str, ok: Any = None) -> Any:
            v = content.get(key)
            if isinstance(v, str) and (ok is None or v in ok):
                return v
            raw = _hex(r[key])  # the display column, undecodable bytes replaced (the chain reports it broken)
            return raw if ok is None or raw in ok else ok[0]

        return m.LedgerRecord(
            chain_index=r["chain_index"], record_id=field("record_id"),
            type=field("type", ("projected", "verified")), created_at=field("created_at"),
            quantity_tco2e=field("quantity_tco2e"), content=content, canonical=canonical_text(r["canonical"]),
            previous_hash=_hex(r["previous_hash"]), hash=_hex(r["hash"]), link_ok=self._link_ok(r["chain_index"]),
        )  # fmt: skip

    # ---- checklist ----------------------------------------------------------------------------------
    def _plan_row(self, plan_id: str) -> dict[str, Any]:
        """The plan's applied version, else its latest (404 when there is no such plan). Blocking."""
        rows = self._repo.query(
            "SELECT * FROM restoration_plans WHERE plan_id = ? "
            "ORDER BY status = 'applied' DESC, version DESC LIMIT 1",
            (plan_id,), table="restoration_plans",
        )  # fmt: skip
        if not rows:
            raise ApiError("not_found", 404, f"No plan {plan_id}.")
        return rows[0]

    @staticmethod
    def _zones(plan: dict[str, Any]) -> list[str]:
        return sorted({i["zone_id"] for i in plan["items"] or []})

    def _cover(self, zones: list[str]) -> dict[str, list[str]]:
        """Per plan zone: its covering WQ and SP nodes."""
        cover = by_zone(self._registry.nodes(), self._grid)
        return {
            z: sorted({*cover.get(z, {}).get("water", []), *cover.get(z, {}).get("soil", [])}) for z in zones
        }

    def _forecast_row(self, plan: dict[str, Any]) -> dict[str, Any] | None:
        return self._repo.get("forecasts", {"id": plan["forecast_id"]}) if plan["forecast_id"] else None

    def _checklist(self, plan: dict[str, Any]) -> m.EvidenceChecklist:
        zones = self._zones(plan)
        forecast = self._forecast_row(plan)
        got = {
            "satellite": bool(self._repo.query("SELECT id FROM captures WHERE evidence_grade = 1 LIMIT 1")),
            "sensor": bool(zones) and all(self._cover(zones).values()),
            "ai": forecast is not None and forecast["status"] == "ready" and bool(forecast["parameters"]),
            "restoration": plan["status"] == "applied",
        }
        return m.EvidenceChecklist(
            plan_id=plan["plan_id"], **got, missing=[k for k in CHECKLIST_KEYS if not got[k]]
        )

    def checklist(self, plan_id: str) -> m.EvidenceChecklist:
        """Blocking."""
        return self._checklist(self._plan_row(plan_id))

    # ---- Projected ----------------------------------------------------------------------------------
    async def create_projected(self, plan_id: str) -> m.LedgerRecord:
        async with self._lock:
            existing, content = await asyncio.to_thread(self._projected, plan_id)
            if existing is not None:
                return existing
            return await self._append(content)

    def _projected(self, plan_id: str) -> tuple[m.LedgerRecord | None, dict[str, Any]]:
        """(the record this plan version already has, {}) or (None, the new record's content). Blocking."""
        plan = self._plan_row(plan_id)
        if plan["status"] == "applied":  # read from the canonical content (a display column could be edited)
            for index, c in stored_contents(self._repo):
                ev = c.get("evidence") or {}
                if c.get("type") == "projected" and ev.get("plan_id") == plan["plan_id"]                         and ev.get("plan_version") == plan["version"]:  # fmt: skip
                    rows = self._repo.query(
                        f"{SELECT_RECORD} FROM {TABLE} WHERE chain_index = ?", (index,), table=TABLE
                    )
                    return self._model(rows[0]), {}
        checklist = self._checklist(plan)
        if checklist.missing:
            raise ApiError(
                "validation_error", 422,
                f"The evidence checklist is incomplete: {', '.join(checklist.missing)}.",
                {"checklist": checklist.model_dump(mode="json")},
            )  # fmt: skip
        return None, self._projected_content(plan)

    def zone_confidence(self, zone: str, prediction: float) -> dict[str, float]:
        """N4 ledger confidence of a zone: camera and sensor from its latest assessment, the given forecast
        prediction component. Blocking."""
        rows = self._repo.query(
            "SELECT confidence FROM zone_assessments WHERE zone_id = ? ORDER BY at DESC, id DESC LIMIT 1",
            (zone,), table="zone_assessments",
        )  # fmt: skip
        c = rows[0]["confidence"] if rows else {}
        camera = float(c.get("camera", NO_COMPONENT))
        sensor = float(c.get("sensor", NO_COMPONENT))
        return {"camera": camera, "sensor": sensor, "prediction": prediction,
                "overall": overall(camera, sensor, prediction, self._settings)}  # fmt: skip

    def _projected_content(self, plan: dict[str, Any]) -> dict[str, Any]:
        zones = self._zones(plan)
        forecast_row = self._forecast_row(plan)
        assert forecast_row is not None  # the checklist's ai item
        forecast = self._forecasts.get(forecast_row["id"])
        gross = self._carbon.plan_additionality(forecast, zones)
        predictions = self._forecasts.zone_predictions(forecast_row)
        conf = {z: self.zone_confidence(z, predictions.get(z, 0.0)) for z in zones}
        record_conf = _dec(min(c["overall"] for c in conf.values()))
        zone_q: dict[str, Any] = {}
        totals = dict.fromkeys(("gross", "buffer", "uncertainty", "net"), Decimal(0))
        fraction = Decimal(0)
        for z in zones:
            g = max(gross[z], Decimal(0))  # a plan that loses carbon credits nothing, never a negative
            d = self._carbon.deductions(g, record_conf)
            fraction = d.uncertainty_fraction
            for k, v in (("gross", g), ("buffer", d.buffer_tco2e), ("uncertainty", d.uncertainty_tco2e),
                         ("net", d.net_tco2e)):  # fmt: skip
                totals[k] += v
            zone_q[z] = {
                "gross_tco2e": fmt_tco2e(g), "buffer_tco2e": fmt_tco2e(d.buffer_tco2e),
                "uncertainty_fraction": fmt_frac(d.uncertainty_fraction),
                "uncertainty_tco2e": fmt_tco2e(d.uncertainty_tco2e), "net_tco2e": fmt_tco2e(d.net_tco2e),
                "confidence": fmt_frac(_dec(conf[z]["overall"])),
            }  # fmt: skip
        cfg = self._carbon.CFG
        return {
            "type": "projected",
            "site_id": self._site_id,
            "zone_ids": zones,
            "period": {
                "start_year": int(cfg.crediting_period.get("start_year", 2026)),
                "end_year": int(cfg.crediting_period.get("end_year", 2035)),
            },
            "quantity_tco2e": fmt_tco2e(totals["net"]),
            "gross_tco2e": fmt_tco2e(totals["gross"]),
            "deductions": {
                "buffer_pct": fmt_pct(_dec(cfg.buffer_pct.value, 2)),
                "buffer_tco2e": fmt_tco2e(totals["buffer"]),
                "uncertainty_fraction": fmt_frac(fraction),
                "uncertainty_tco2e": fmt_tco2e(totals["uncertainty"]),
            },
            "zone_quantities": zone_q,
            "confidence": {
                "overall": fmt_frac(record_conf),
                "zones": {z: {k: fmt_frac(_dec(v)) for k, v in c.items()} for z, c in conf.items()},
            },
            "evidence": self._evidence(plan, forecast_row, zones),
            "demo_time_scale": self._settings.demo_time_scale == "on",
            "projected_record_id": None,
        }

    # ---- evidence -----------------------------------------------------------------------------------
    def _evidence(self, plan: dict[str, Any], forecast: dict[str, Any], zones: list[str]) -> dict[str, Any]:
        return {
            "captures": self._evidence_captures(plan),
            "telemetry_window": self.telemetry_window(zones),
            "forecast_id": forecast["id"],
            "plan_id": plan["plan_id"],
            "plan_version": plan["version"],
            "ai_calls": self._ai_calls(plan, forecast, zones),
        }

    def _evidence_captures(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        def entry(row: dict[str, Any] | None, role: str) -> list[dict[str, Any]]:
            return [] if row is None else [{"id": row["id"], "role": role, "taken_at": row["taken_at"]}]

        baseline = self._repo.query(
            "SELECT id, taken_at FROM captures WHERE is_baseline = 1 ORDER BY taken_at DESC LIMIT 1"
        )
        app_id = plan["capture_at_application_id"]
        application = self._repo.get("captures", {"id": app_id}) if app_id else None
        latest = self._repo.query(
            "SELECT id, taken_at FROM captures WHERE evidence_grade = 1 ORDER BY taken_at DESC, id DESC LIMIT ?",
            (LATEST_CAPTURES,),
        )
        out = entry(baseline[0] if baseline else None, "baseline") + entry(application, "application")
        for r in latest:
            out += entry(r, "latest")
        return out

    def telemetry_window(self, zones: list[str], start: datetime | None = None) -> dict[str, Any]:
        """The covering nodes' samples from ``start`` (default: the last ``TELEMETRY_WINDOW_S``) to now,
        summarised per node; always marked simulated (evidence honesty). Blocking."""
        nodes = sorted({n for ns in self._cover(zones).values() for n in ns})
        end = self._clock.now()
        start = end - timedelta(seconds=TELEMETRY_WINDOW_S) if start is None else start
        stats: dict[str, Any] = {}
        if nodes:
            marks = ", ".join("?" * len(nodes))
            rows = self._repo.query(
                f"SELECT node_id, readings FROM telemetry WHERE node_id IN ({marks}) "
                "AND sampled_at >= ? AND sampled_at <= ? ORDER BY sampled_at",
                (*nodes, to_iso(start), to_iso(end)), table="telemetry",
            )  # fmt: skip
            values: dict[str, dict[str, list[float]]] = {}
            for r in rows:
                for k, v in (r["readings"] or {}).items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        values.setdefault(r["node_id"], {}).setdefault(k, []).append(float(v))
            for n in nodes:
                per = values.get(n, {})
                stats[n] = {
                    "samples": max((len(v) for v in per.values()), default=0),
                    "readings": {
                        k: {"min": _stat(min(v)), "mean": _stat(sum(v) / len(v)), "max": _stat(max(v))}
                        for k, v in sorted(per.items())
                    },
                }
        return {
            "node_ids": nodes,
            "from": to_iso(start),
            "to": to_iso(end),
            "stats": stats,
            "simulated": True,
        }

    def _ai_calls(
        self, plan: dict[str, Any], forecast: dict[str, Any], zones: list[str]
    ) -> list[dict[str, Any]]:
        out = []
        if plan["ai_call_id"]:
            call = self._repo.get("ai_calls", {"id": plan["ai_call_id"]})
            if call is not None:
                out.append(
                    {"role": call["role"], "id": call["id"], "tier": call["tier"], "model": call["model"]}
                )
        elif plan["source"] in ("ai", "mixed"):
            out.append({"role": "restoration_planner", "id": None, "tier": "rules", "model": None})
        sources = forecast["parameter_sources"] or {}
        for z in zones:
            src = sources.get(z)
            if src is None:
                continue
            out.append({
                "role": "forecast_parameter_estimator", "zone_id": z, "id": src.get("ai_call_id"),
                "tier": src.get("tier"), "model": src.get("model"), "cached": bool(src.get("cached")),
            })  # fmt: skip
        return out

    # ---- the single writer --------------------------------------------------------------------------
    async def append(self, content: dict[str, Any]) -> m.LedgerRecord:
        async with self._lock:
            return await self._append(content)

    async def _append(self, content: dict[str, Any]) -> m.LedgerRecord:
        missing = [k for k in REQUIRED if k not in content]
        if missing:
            raise ValueError(f"ledger content is missing {missing}")
        record = await asyncio.to_thread(self._store, content)
        data = {"chain_index": record.chain_index, "record_id": record.record_id, "type": record.type,
                "quantity_tco2e": record.quantity_tco2e}  # fmt: skip
        self._bus.publish("ledger.appended", data)
        self._alerts.raise_(
            "ledger_issued", message=f"{record.record_id} issued: {record.type} {record.quantity_tco2e} tCO2e",
            details=data,
        )  # fmt: skip
        return record

    def _store(self, content: dict[str, Any]) -> m.LedgerRecord:
        now = self._clock.now()
        year = now.year
        with self._repo.transaction():
            last = self._repo.query(
                f"SELECT chain_index, hash FROM {TABLE} ORDER BY chain_index DESC LIMIT 1", table=TABLE
            )
            seqs = self._repo.query(
                f"SELECT record_id FROM {TABLE} WHERE record_id LIKE ?", (f"BC-{year:04d}-%",), table=TABLE
            )
            seq = max((int(r["record_id"].rsplit("-", 1)[1]) for r in seqs), default=0) + 1
            full = {
                "projected_record_id": None,
                **content,
                # always the exact wording, whatever the caller passed (spec 23; M6 Global Constraints)
                "label": LABEL, "method_note": METHOD_NOTE,
                "chain_index": last[0]["chain_index"] + 1 if last else 0,
                "record_id": ledger_record_id(year, seq),
                "created_at": to_iso(now),
                "previous_hash": last[0]["hash"] if last else GENESIS_PREV,
            }  # fmt: skip
            canonical = canonical_json(full)
            row = {k: full[k] for k in COLUMNS}
            row.update(canonical=canonical, previous_hash=full["previous_hash"], hash=record_hash(canonical))
            self._repo.insert(TABLE, row)
        for cid in sorted(evidence_capture_ids(full["evidence"])):
            try:
                self._captures.mark_referenced(cid, "ledger_evidence")  # H7, A2
            except CaptureNotFound:
                continue
        return self._model(row)

    async def startup_verify(self) -> None:
        """Verify the stored chain once at startup so ``link_ok`` is populated after a restart (cheap at
        demo sizes). Skipped on an empty ledger; failures never stop startup."""
        try:
            has = await asyncio.to_thread(self._repo.query, f"SELECT 1 FROM {TABLE} LIMIT 1", (), table=TABLE)
            if has:
                await self.verify_chain()
        except Exception:
            log.warning("startup ledger verification failed", exc_info=True)

    # ---- verification -------------------------------------------------------------------------------
    async def verify_chain(self) -> m.ChainVerification:
        rows = await asyncio.to_thread(self._repo.query, VERIFY_SQL)
        v = verify([_stored(r) for r in rows], at=to_iso(self._clock.now()))
        self._last = v
        self.issuance_blocked = not v.intact
        out = m.ChainVerification(intact=v.intact, checked=v.checked, first_broken_index=v.first_broken_index,
                                  at=v.at)  # fmt: skip
        self._bus.publish("ledger.verified", out.model_dump(mode="json"))
        if not v.intact:
            self._alerts.raise_(
                "chain_broken", message=f"Ledger chain broken at index {v.first_broken_index}: issuance stopped",
                details={"first_broken_index": v.first_broken_index, "checked": v.checked},
            )  # fmt: skip
        return out


# Every value the chain checks, read as a BLOB (decoded strictly in ``ledger.chain``), so a crafted row is a
# broken record and never an exception. Display columns are aliased so the repo leaves them undecoded.
VERIFY_SQL = (
    f"SELECT chain_index, {CANONICAL_BLOB}, CAST(hash AS BLOB) AS hash, "
    "CAST(previous_hash AS BLOB) AS previous_hash, "
    + ", ".join(f'CAST("{c}" AS BLOB) AS "col_{c}"' for c in DISPLAY_COLUMNS)
    + f" FROM {TABLE} ORDER BY chain_index"
)


def _hex(raw: Any) -> str:
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)


def _stored(r: dict[str, Any]) -> StoredRecord:
    return StoredRecord(
        chain_index=r["chain_index"], canonical=r["canonical"], hash=_hex(r["hash"]),
        previous_hash=_hex(r["previous_hash"]), columns={c: r[f"col_{c}"] for c in DISPLAY_COLUMNS},
    )  # fmt: skip
