"""EvidencePackBuilder (spec 24; addendum H2 ``evidence_packs``, H5, I2): the 8-section PDF of one ledger
record, written to ``evidence-packs/{record_id}.pdf`` with one insert-only ``evidence_packs`` row.

``build`` is blocking and CPU-bound. ``get_or_build`` runs it on a worker thread and serialises builds of
the same record, so concurrent requests produce one file and one row. Sections, in order: 1 cover, 2 chain
proof (the chain is verified at generation through ``LedgerService.verify_chain``, so a broken chain found
here raises ``chain_broken`` and stops issuance like any other verification), 3 camera evidence (real captures; a capture whose files are
gone prints "image not available for this capture"), 4 sensor evidence (always SIMULATED), 5 forecast and
plan, 6 AI provenance, 7 methodology, constants and confidence, 8 disclaimers. Times are shown in MYT (F2).
"""

from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import matplotlib
from bcs_protocol.timefmt import from_iso, to_iso
from fpdf import FPDF
from fpdf.fonts import FontFace
from PIL import Image

from bcs_gs.api.errors import ApiError
from bcs_gs.api.routes_media import change_map_png
from bcs_gs.capture.artefacts import BUCKET as CAPTURES
from bcs_gs.core.ids import uuid7
from bcs_gs.evidence import charts

BUCKET = "evidence-packs"
LABEL = "Demo record — not a certified carbon credit"
FONTS = Path(__file__).resolve().parent / "fonts"
DEJAVU = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
MAX_CHARTS = 8
NO_IMAGE = "image not available for this capture"
DISCLAIMERS = (
    (
        "This is a demo record produced by a hackathon prototype. It is not a certified carbon credit, it "
        "has not been validated or verified by any standards body, and it must not be traded, claimed or "
        "offset."
    ),
    (
        "Sensor data in this pack is SIMULATED. Camera evidence comes from the demo camera over a model of "
        "the site, not from a real mangrove."
    ),
    (
        "Quantities are projections from a forecast model with cited constants. Their uncertainty is stated "
        "in the confidence breakdown and withheld through the buffer and uncertainty deductions."
    ),
    (
        "The hash chain proves the record was not edited after it was written. It does not prove that the "
        "evidence is real."
    ),
)
GROSS_NOTE = (
    "Gross additionality is clamped at zero per zone: a plan that loses carbon credits nothing and never "
    "yields a negative quantity. Avoided soil carbon is never credited; only avoided biomass loss counts."
)


def myt(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        return from_iso(iso).astimezone(charts.MYT).strftime("%Y-%m-%d %H:%M:%S MYT")
    except (ValueError, TypeError):
        return str(iso)


class _Pdf(FPDF):
    def __init__(self, record_id: str) -> None:
        super().__init__(format="A4")
        self.record_id = record_id
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(True, margin=18)
        self.add_font("Inter", "", str(FONTS / "Inter-Regular.ttf"))
        self.add_font("Inter", "B", str(FONTS / "Inter-Bold.ttf"))
        self.add_font("Mono", "", str(FONTS / "JetBrainsMono-Regular.ttf"))
        self.add_font("Mono", "B", str(FONTS / "JetBrainsMono-Bold.ttf"))
        self.add_font("DejaVu", "", str(DEJAVU))  # glyphs Inter lacks (the check mark)
        self.set_fallback_fonts(["DejaVu"])
        self.set_font("Inter", "", 10)
        self.alias_nb_pages("{nb}")

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Inter", "", 7.5)
        self.set_text_color(90, 90, 90)
        self.cell(0, 5, f"{LABEL} · {self.record_id} · page {self.page_no()}/{{nb}}", align="C")
        self.set_text_color(0, 0, 0)

    # ---- layout helpers -----------------------------------------------------------------------
    def h1(self, text: str) -> None:
        self.set_font("Inter", "B", 15)
        self.cell(0, 9, text, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Inter", "", 10)

    def h2(self, text: str) -> None:
        self.ln(2)
        self.set_font("Inter", "B", 11)
        self.cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Inter", "", 10)

    def para(self, text: str, size: float = 10, bold: bool = False) -> None:
        self.set_font("Inter", "B" if bold else "", size)
        self.multi_cell(0, size * 0.5, text, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Inter", "", 10)
        self.ln(1)

    def kv(self, rows: list[tuple[str, str]], mono: bool = False) -> None:
        for k, v in rows:
            self.set_font("Inter", "B", 9)
            self.cell(38, 5.5, k)
            self.set_font("Mono" if mono else "Inter", "", 8 if mono else 9)
            self.multi_cell(0, 5.5, v, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Inter", "", 10)

    def grid(
        self, head: list[str], rows: list[list[str]], widths: list[float], size: float = 8,
        mono_cols: tuple[int, ...] = (),
    ) -> None:
        """A table. Columns in ``mono_cols`` (IDs) are set in the mono face, 1 pt smaller, so they fit unbroken."""
        self.set_font("Inter", "", size)
        with self.table(col_widths=widths, text_align="LEFT", line_height=size * 0.5) as t:
            r = t.row()
            for h in head:
                r.cell(h, style=None)
            for row in rows:
                r = t.row()
                for i, c in enumerate(row):
                    if i in mono_cols:
                        r.cell(str(c), style=FontFace(family="Mono", size_pt=size - 1))
                    else:
                        r.cell(str(c))
        self.set_font("Inter", "", 10)
        self.ln(2)

    def png(self, data: bytes, w: float) -> None:
        img = Image.open(io.BytesIO(data))
        h = w * img.height / img.width
        if self.get_y() + h > self.page_break_trigger:
            self.add_page()
        self.image(io.BytesIO(data), x=self.l_margin, y=self.get_y(), w=w)
        self.set_y(self.get_y() + h + 2)

    def badge(self, text: str) -> None:
        self.set_fill_color(180, 35, 24)
        self.set_text_color(255, 255, 255)
        self.set_font("Inter", "B", 11)
        self.cell(
            self.get_string_width(text) + 8, 7, text, fill=True, align="C", new_x="LMARGIN", new_y="NEXT"
        )
        self.set_text_color(0, 0, 0)
        self.set_font("Inter", "", 10)
        self.ln(2)


class EvidencePackBuilder:
    def __init__(
        self, *, repo: Any, media: Any, ledger: Any, forecasts: Any, clock: Any, carbon: Any
    ) -> None:
        self._repo, self._media, self._ledger = repo, media, ledger
        self._forecasts, self._clock, self._carbon = forecasts, clock, carbon
        self._locks: dict[str, asyncio.Lock] = {}

    def reset(self) -> None:
        self._locks.clear()

    # ---- entry points ---------------------------------------------------------------------------
    async def get_or_build(self, record_id: str) -> Path:
        lock = self._locks.setdefault(record_id, asyncio.Lock())
        async with lock:
            path = await asyncio.to_thread(self._stored, record_id)
            if path is not None:
                return path
            await asyncio.to_thread(self._ledger.get, record_id)  # 404 before verifying anything
            v = await self._ledger.verify_chain()  # the real verification: chain_broken, issuance_blocked
            return await asyncio.to_thread(self.build, record_id, (v.intact, v.checked, v.first_broken_index))

    def _row(self, record_id: str) -> dict[str, Any] | None:
        rows = self._repo.query(
            "SELECT * FROM evidence_packs WHERE record_id = ?", (record_id,), table="evidence_packs"
        )
        return rows[0] if rows else None

    def _stored(self, record_id: str) -> Path | None:
        row = self._row(record_id)
        if row is not None:
            path = self._media.path(BUCKET, row["media_key"])
            if path.is_file():
                return path
        return None

    def build(self, record_id: str, verification: tuple[bool, int, int | None]) -> Path:
        """Render the pack, store it and record it (one row per record; a rebuild after the file was lost
        rewrites the file only). ``verification`` is (intact, checked, first broken index) of the chain
        verification the caller just ran."""
        rec = self._ledger.get(record_id)  # 404 for an unknown record
        intact, checked, broken = verification
        data = bytes(self._render(rec, intact, checked, broken).output())
        key = f"{record_id}.pdf"
        path = self._media.put(BUCKET, key, data, "application/pdf", protected=True, cloud=True)
        if self._row(record_id) is None:
            self._repo.insert("evidence_packs", {
                "id": uuid7(), "record_id": record_id, "media_key": key,
                "generated_at": self._now_iso(), "chain_intact": intact, "bytes": len(data),
            })  # fmt: skip
        return path

    def _now_iso(self) -> str:
        return to_iso(self._clock.now())

    # ---- the document ---------------------------------------------------------------------------
    def _render(self, rec: Any, intact: bool, checked: int, broken: int | None) -> _Pdf:
        c = rec.content
        ev = c.get("evidence") or {}
        pdf = _Pdf(rec.record_id)
        pdf.add_page()
        self._cover(pdf, rec, c)
        self._chain(pdf, rec, intact, checked, broken)
        self._camera(pdf, c, ev)
        self._sensors(pdf, ev.get("telemetry_window") or {})
        self._forecast(pdf, c, ev)
        self._ai(pdf, ev)
        self._method(pdf, c)
        self._disclaimers(pdf)
        return pdf

    def _cover(self, pdf: _Pdf, rec: Any, c: dict[str, Any]) -> None:
        pdf.h1("1. Cover")
        pdf.para("Blue Carbon Sentinel evidence pack", 13)
        status = "Verified (demo)" if rec.type == "verified" else "Projected (demo)"
        period = c.get("period") or {}
        rows = [
            ("Record ID", rec.record_id), ("Type", rec.type.capitalize()),
            ("Quantity", f"{c.get('quantity_tco2e')} tCO₂e"), ("Status", status),
            ("Created", myt(rec.created_at)), ("Site", str(c.get("site_id"))),
            ("Zones", ", ".join(c.get("zone_ids") or [])),
            ("Crediting period", f"{period.get('start_year')}–{period.get('end_year')}"),
        ]  # fmt: skip
        if c.get("projected_record_id"):
            rows.append(("Projected record", c["projected_record_id"]))
        pdf.kv(rows)
        pdf.ln(3)
        pdf.para(LABEL, 12, bold=True)
        pdf.para(str(c.get("method_note") or ""), 9)

    def _chain(self, pdf: _Pdf, rec: Any, intact: bool, checked: int, broken: int | None) -> None:
        pdf.ln(4)
        pdf.h1("2. Chain proof")
        pdf.kv([("Chain index", str(rec.chain_index)), ("Hash (SHA-256)", rec.hash),
                ("Previous hash", rec.previous_hash)], mono=True)  # fmt: skip
        result = (f"INTACT — {checked} record(s) verified" if intact
                  else f"BROKEN at index {broken} — {checked} record(s) verified before the break")  # fmt: skip
        pdf.kv([("Verification", f"{result}, at generation {myt(self._now_iso())}")])
        pdf.para("The hash is SHA-256 over the canonical JSON of the record (sorted keys, compact separators, "
                 "UTF-8).", 8.5)  # fmt: skip

    # -- 3 ---------------------------------------------------------------------------------------
    def _file(self, row: dict[str, Any] | None, kind: str) -> Path | None:
        key = ((row or {}).get("media") or {}).get(kind)
        if not key:
            return None
        try:
            path = self._media.path(CAPTURES, key)
        except ValueError:
            return None
        return path if path.is_file() else None

    def _camera(self, pdf: _Pdf, c: dict[str, Any], ev: dict[str, Any]) -> None:
        pdf.add_page()
        pdf.h1("3. Camera evidence")
        caps = ev.get("captures") or []
        pdf.para(
            "Site rasters from the demo camera ('satellite' stand-in), the NDVI proxy (VARI) and the change "
            "map between the before and after captures.",
            9,
        )
        if not caps:
            pdf.para("No captures are cited by this record.")
            return
        pick = {x["role"]: x for x in caps}
        before = pick.get("baseline") or pick.get("application") or caps[0]
        after = caps[-1]
        rows = {x["id"]: self._repo.get("captures", {"id": x["id"]}) for x in (before, after)}
        for label, cap in (("Before", before), ("After", after)):
            pdf.h2(f"{label}: {cap['role']} capture")
            pdf.kv([("Capture ID", cap["id"]), ("Taken", myt(cap.get("taken_at")))])
            img = self._file(rows[cap["id"]], "image")
            if img is None:
                pdf.para(NO_IMAGE, 9)
            else:
                buf = io.BytesIO()
                Image.open(img).convert("RGB").save(buf, "PNG")
                pdf.png(buf.getvalue(), 80)
        b_ndvi, a_ndvi = self._file(rows[before["id"]], "ndvi"), self._file(rows[after["id"]], "ndvi")
        pdf.h2("NDVI proxy and change map")
        vari = cv2.imread(str(a_ndvi), cv2.IMREAD_UNCHANGED) if a_ndvi else None
        if vari is None or vari.ndim != 2:
            pdf.para(f"NDVI proxy: {NO_IMAGE}", 9)
        else:
            pdf.png(charts.ndvi_proxy_png(vari.astype("float32") / 65535.0 * 2.0 - 1.0), 80)
        if a_ndvi is None or b_ndvi is None or before["id"] == after["id"]:
            pdf.para(f"Change map: {NO_IMAGE}", 9)
        else:
            try:
                pdf.png(change_map_png(b_ndvi, a_ndvi), 80)
            except (ApiError, RuntimeError):
                pdf.para(f"Change map: {NO_IMAGE}", 9)
        self._metrics_table(pdf, c, caps)

    def _metrics_table(self, pdf: _Pdf, c: dict[str, Any], caps: list[dict[str, Any]]) -> None:
        pdf.h2("Zone metrics")
        out: list[list[str]] = []
        seen: set[str] = set()
        for cap in caps:
            if cap["id"] in seen:
                continue
            seen.add(cap["id"])
            for z in c.get("zone_ids") or []:
                m = self._repo.get("zone_metrics", {"capture_id": cap["id"], "zone_id": z})
                if m is None:
                    continue
                out.append([cap["id"], cap["role"], myt(cap.get("taken_at")), z, f"{m['canopy_pct']:.1f}",
                            f"{m['water_pct']:.1f}", f"{m['mud_pct']:.1f}", f"{m['dieback_pct']:.1f}",
                            f"{m['new_growth_pct']:.1f}"])  # fmt: skip
        if not out:
            pdf.para("No zone metrics are stored for the cited captures.", 9)
            return
        pdf.grid(["Capture ID", "Role", "Taken (MYT)", "Zone", "Canopy %", "Water %", "Mud %", "Dieback %",
                  "New growth %"], out, [48, 16, 28, 14, 13, 12, 12, 14, 15], 6.5, mono_cols=(0,))  # fmt: skip

    # -- 4 ---------------------------------------------------------------------------------------
    def _samples(self, node: str, win: dict[str, Any]) -> list[tuple[datetime, dict[str, float]]]:
        rows = self._repo.query(
            "SELECT sampled_at, readings FROM telemetry WHERE node_id = ? AND sampled_at >= ? "
            "AND sampled_at <= ? ORDER BY sampled_at",
            (node, win.get("from"), win.get("to")), table="telemetry",
        )  # fmt: skip
        return [(from_iso(r["sampled_at"]),
                 {k: float(v) for k, v in (r["readings"] or {}).items()
                  if isinstance(v, (int, float)) and not isinstance(v, bool)}) for r in rows]  # fmt: skip

    def _sensors(self, pdf: _Pdf, win: dict[str, Any]) -> None:
        pdf.add_page()
        pdf.h1("4. Sensor evidence")
        pdf.badge("SIMULATED")
        nodes = win.get("node_ids") or []
        pdf.kv([("Window", f"{myt(win.get('from'))} to {myt(win.get('to'))}"),
                ("Covering nodes", ", ".join(nodes) or "none")])  # fmt: skip
        pdf.para("All sensor readings in this pack are SIMULATED by the demo node simulator.", 9)
        stats = win.get("stats") or {}
        for node in nodes[:MAX_CHARTS]:
            pdf.h2(node)
            s = (stats.get(node) or {}).get("readings") or {}
            if s:
                pdf.grid(
                    ["Reading", "Min", "Mean", "Max"],
                    [[k, v["min"], v["mean"], v["max"]] for k, v in s.items()],
                    [60, 40, 40, 40],
                    7.5,
                )
            pdf.png(charts.sensor_chart_png(node, self._samples(node, win)), 170)

    # -- 5 ---------------------------------------------------------------------------------------
    def _forecast(self, pdf: _Pdf, c: dict[str, Any], ev: dict[str, Any]) -> None:
        pdf.add_page()
        pdf.h1("5. Forecast and plan summary")
        plan = self._repo.query(
            "SELECT * FROM restoration_plans WHERE plan_id = ? AND version = ?",
            (ev.get("plan_id"), ev.get("plan_version")), table="restoration_plans",
        ) if ev.get("plan_id") else []  # fmt: skip
        pdf.kv([("Plan", f"{ev.get('plan_id')} version {ev.get('plan_version')}"),
                ("Forecast", str(ev.get("forecast_id")))])  # fmt: skip
        if plan:
            pdf.grid(["Zone", "Interventions", "Priority", "Rationale"],
                     [[i["zone_id"], ", ".join(self._intervention(x) for x in i["interventions"]),
                       str(i["priority"]), i["rationale"]] for i in plan[0]["items"] or []],
                     [20, 60, 14, 86], 7.5)  # fmt: skip
        if not ev.get("forecast_id"):
            pdf.para("No forecast is recorded for this record.")
            return
        try:
            f = self._forecasts.get(ev["forecast_id"])
        except ApiError:
            pdf.para("The forecast is no longer available.")
            return
        pdf.para("Bands are the low / central / high runs of the forecast. Canopy is shown in percent.", 9)
        rows: list[list[str]] = []
        for z in (c.get("zone_ids") or [])[:4]:
            wo, wi = f.scenarios.without.zones.get(z), f.scenarios.with_.zones.get(z)
            if not wo or not wi:
                continue
            for p0, p1 in zip(wo, wi, strict=False):
                if p0.year in (2030, 2035):
                    rows.append([z, str(p0.year), self._band(p0.canopy, 100), self._band(p1.canopy, 100),
                                 self._band(p1.additional_tco2e)])  # fmt: skip
            pdf.png(
                charts.forecast_chart_png(
                    z,
                    [p.year for p in wo],
                    [self._tri(p.canopy, 100) for p in wo],
                    [self._tri(p.canopy, 100) for p in wi],
                    "canopy %",
                    "canopy, without vs with plan",
                ),
                170,
            )
        if rows:
            pdf.grid(
                [
                    "Zone",
                    "Year",
                    "Canopy % without (low / central / high)",
                    "Canopy % with",
                    "Additional tCO₂e (low / central / high)",
                ],
                rows,
                [18, 12, 52, 52, 46],
                7.5,
            )

    @staticmethod
    def _tri(b: Any, k: float = 1.0) -> tuple[float, float, float]:
        return (b.low * k, b.central * k, b.high * k)

    @classmethod
    def _band(cls, b: Any, k: float = 1.0) -> str:
        lo, mid, hi = cls._tri(b, k)
        return f"{lo:.2f} / {mid:.2f} / {hi:.2f}"

    @staticmethod
    def _intervention(i: dict[str, Any]) -> str:
        n = i.get("sapling_count")
        return f"{i['kind']} ({n} saplings)" if n else str(i["kind"])

    # -- 6 ---------------------------------------------------------------------------------------
    def _ai(self, pdf: _Pdf, ev: dict[str, Any]) -> None:
        pdf.add_page()
        pdf.h1("6. AI provenance")
        calls = ev.get("ai_calls") or []
        if not calls:
            pdf.para("No AI calls are cited by this record.")
            return
        rows = []
        for a in calls:
            row = self._repo.get("ai_calls", {"id": a["id"]}) if a.get("id") else None
            cached = a.get("cached", bool(row["cache_hit"]) if row else False)
            rows.append([a.get("role", ""), a.get("zone_id") or "", a.get("tier") or "-", a.get("model") or "-",
                         myt(row["at"]) if row else "-", "✓ cached" if cached else "fresh"])  # fmt: skip
        pdf.grid(["Role", "Zone", "Tier", "Model", "Time (MYT)", "Cache"], rows,
                 [40, 18, 18, 42, 40, 22], 7.5)  # fmt: skip

    # -- 7 ---------------------------------------------------------------------------------------
    def _method(self, pdf: _Pdf, c: dict[str, Any]) -> None:
        pdf.add_page()
        pdf.h1("7. Methodology and constants")
        pdf.para(str(c.get("method_note") or ""), 10)
        pdf.para(
            "Additionality over the crediting period is cohort sequestration plus avoided biomass loss "
            "(with plan minus without). " + GROSS_NOTE,
            9,
        )
        pdf.para(
            "Deductions: a buffer, then an uncertainty deduction of clamp((1 − overall confidence) − 0.10, "
            "0, 0.5) × quantity. Net quantity = gross − buffer − uncertainty.",
            9,
        )
        d = c.get("deductions") or {}
        pdf.kv([("Gross", f"{c.get('gross_tco2e')} tCO₂e"),
                ("Buffer", f"{d.get('buffer_pct', '')} % = {d.get('buffer_tco2e')} tCO₂e"),
                ("Uncertainty", f"{d.get('uncertainty_fraction')} = {d.get('uncertainty_tco2e')} tCO₂e"),
                ("Net quantity", f"{c.get('quantity_tco2e')} tCO₂e")])  # fmt: skip
        if c.get("verification"):
            v = c["verification"]
            ratio = f"{c.get('verification_ratio')} (observed {v.get('observed_pp')} pp, expected {v.get('expected_pp')} pp)"
            pdf.kv([("Verification ratio", ratio)])
        pdf.h2("Constants and citations")
        cfg = self._carbon.CFG
        rows = [[n, str(k.value), k.unit, k.citation, k.source_url] for n, k in (
            ("ecosystem_density", cfg.ecosystem_density_mg_c_ha), ("biomass_density", cfg.biomass_density_mg_c_ha),
            ("co2e_per_c", cfg.co2e_per_c), ("buffer_pct", cfg.buffer_pct))]  # fmt: skip
        rows.append(["cohort_rates", json.dumps(cfg.cohort_rates.value), cfg.cohort_rates.unit,
                     cfg.cohort_rates.citation, cfg.cohort_rates.source_url])  # fmt: skip
        pdf.grid(["Constant", "Value", "Unit", "Citation", "Source"], rows, [30, 22, 16, 72, 40], 6.5)
        pdf.h2("Confidence breakdown")
        conf = c.get("confidence") or {}
        pdf.para(f"Overall (record, the minimum over zones): {conf.get('overall')}", 9)
        zrows = [[z, *(str(v.get(k, "-")) for k in ("camera", "sensor", "prediction", "overall"))]
                 for z, v in (conf.get("zones") or {}).items()]  # fmt: skip
        if zrows:
            pdf.grid(["Zone", "Camera", "Sensor", "Prediction", "Overall"], zrows, [30, 30, 30, 30, 30], 8)

    def _disclaimers(self, pdf: _Pdf) -> None:
        pdf.add_page()
        pdf.h1("8. Disclaimers")
        pdf.para(LABEL, 11, bold=True)
        for d in DISCLAIMERS:
            pdf.para("• " + d, 9.5)
