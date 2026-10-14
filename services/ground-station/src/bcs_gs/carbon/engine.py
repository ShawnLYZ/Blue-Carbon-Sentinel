"""CarbonEngine (spec section 22; M6): cited stocks, plan additionality and deductions.

Two different quantities, never added (ruling R6):

* **Stock** (``zone_stock``): the standing carbon of the whole ecosystem, soil included, canopy fraction x
  area x 1,074 Mg C/ha (Donato 2011) x 44/12. About 3,900 tCO2e per hectare at full canopy.
* **Additionality** (``plan_additionality``): the extra a plan adds over the crediting period 2026-2035, the
  forecast's cohort sequestration (a flux of a few Mg C/ha/yr) plus the avoided *biomass* loss (with minus
  without). Avoided soil carbon is never credited. It is about two orders of magnitude below the stock.

Quantities are ``Decimal``: tCO2e to 3 dp, fractions to 4 dp, rounded half-even.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

import yaml

from bcs_gs.api import models as m
from bcs_gs.carbon.core import stock_tco2e
from bcs_gs.core.config import Carbon
from bcs_gs.ledger.contents import stored_contents, verified_key

_CONFIG = Path(__file__).resolve().parents[5] / "config" / "carbon.yaml"
CFG: Carbon = Carbon.model_validate(yaml.safe_load(_CONFIG.read_text(encoding="utf-8")))

_Q3 = Decimal("0.001")
_Q4 = Decimal("0.0001")


@dataclass(frozen=True)
class Deductions:
    buffer_tco2e: Decimal
    uncertainty_fraction: Decimal
    uncertainty_tco2e: Decimal
    net_tco2e: Decimal


def _d(x: Any) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def zone_stock(canopy_fraction: float, area_ha: float = 1.0) -> float:
    """Standing carbon stock of a zone in tCO2e (ecosystem density, soil included)."""
    return stock_tco2e(canopy_fraction, area_ha, CFG.ecosystem_density_mg_c_ha.value)


def site_stock(zones: Iterable[float], area_ha: float = 1.0) -> float:
    """Standing stock of the zones (canopy fractions), each of ``area_ha``."""
    return sum(zone_stock(c, area_ha) for c in zones)


def deductions(gross: Decimal, overall_conf: Decimal, buffer_pct: Decimal | None = None) -> Deductions:
    """Buffer first, then the uncertainty deduction on what is left; net rounded half-even to 3 dp."""
    pct = _d(CFG.buffer_pct.value) if buffer_pct is None else _d(buffer_pct)
    offset = _d(CFG.uncertainty.get("offset", 0.10))
    cap = _d(CFG.uncertainty.get("cap", 0.5))
    gross, conf = _d(gross), _d(overall_conf)
    buffer = gross * pct / Decimal(100)
    fraction = min(max((Decimal(1) - conf) - offset, Decimal(0)), cap)
    uncertainty = (gross - buffer) * fraction
    net = gross - buffer - uncertainty
    return Deductions(
        buffer_tco2e=buffer.quantize(_Q3, ROUND_HALF_EVEN),
        uncertainty_fraction=fraction.quantize(_Q4, ROUND_HALF_EVEN),
        uncertainty_tco2e=uncertainty.quantize(_Q3, ROUND_HALF_EVEN),
        net_tco2e=net.quantize(_Q3, ROUND_HALF_EVEN),
    )


def _series(forecast: Any, scenario: str) -> Any:
    sc = forecast.scenarios
    if isinstance(sc, dict):  # engine ForecastResult
        return sc[scenario]
    return sc.with_ if scenario == "with" else sc.without  # api Forecast


def _point(forecast: Any, scenario: str, zone: str, year: int) -> Any:
    pts = _series(forecast, scenario).zones[zone]
    return next(p for p in pts if p.year == year)


def plan_additionality(forecast: Any, zone_ids: Iterable[str]) -> dict[str, Decimal]:
    """Central additional tCO2e at the end of the crediting period (2035) for each zone of the plan."""
    year = CFG.crediting_period.get("end_year", 2035)
    return {
        z: _d(round(_point(forecast, "with", z, year).additional_tco2e.central, 3)).quantize(
            _Q3, ROUND_HALF_EVEN
        )
        for z in zone_ids
    }


def _constants() -> list[m.CarbonConstant]:
    out = [
        m.CarbonConstant(name=n, value=c.value, unit=c.unit, citation=c.citation)
        for n, c in (
            ("ecosystem_density_mg_c_ha", CFG.ecosystem_density_mg_c_ha),
            ("biomass_density_mg_c_ha", CFG.biomass_density_mg_c_ha),
            ("co2e_per_c", CFG.co2e_per_c),
            ("buffer_pct", CFG.buffer_pct),
        )
    ]
    for b in CFG.cohort_rates.value:
        out.append(
            m.CarbonConstant(
                name=f"cohort_rate_age_{int(b['min_age'])}_{int(b['max_age'])}",
                value=b["rate"],
                unit=CFG.cohort_rates.unit,
                citation=CFG.cohort_rates.citation,
            )
        )
    return out


def ledger_totals(repo: Any) -> tuple[Decimal, Decimal]:
    """(projected, verified) tCO2e summed over the ledger without double counting, read from each
    record's hashed canonical content (never the editable display columns).

    Projected = the sum, over plans, of the quantity of each plan's *latest* Projected record: a plan
    version that is re-applied gets a new Projected record that supersedes the earlier version's, so only
    the newest per plan counts. Verified = the sum of the first Verified record per (plan, zone) across
    all plan versions (issuance allows only one; a second would not add to the total).
    """
    latest: dict[str, Decimal] = {}
    seen: set[tuple[str, str]] = set()
    verified = Decimal(0)
    for index, c in stored_contents(repo):
        try:
            q = Decimal(str(c.get("quantity_tco2e")))
        except ArithmeticError:
            continue  # not a quantity: chain verification reports a record like that
        if not q.is_finite():
            continue
        if c.get("type") == "projected":
            plan_id = (c.get("evidence") or {}).get("plan_id")
            latest[str(plan_id) if plan_id else f"record-{index}"] = q  # later chain index wins
        elif (key := verified_key(c)) is not None and key not in seen:
            seen.add(key)
            verified += q
    return sum(latest.values(), Decimal(0)), verified


def summary(repo: Any, canopy: Mapping[str, float]) -> m.CarbonSummary:
    """CarbonSummary (I3). ``canopy`` maps each zone to its current canopy fraction (0..1); stock is the
    standing stock of that canopy. Projected and verified are ledger sums (see ``ledger_totals``). Needs
    no forecast: a zone with no canopy reading counts as zero."""
    per_zone = {z: zone_stock(c) for z, c in sorted(canopy.items())}
    projected, verified = ledger_totals(repo)
    return m.CarbonSummary(
        stock_tco2e=sum(per_zone.values()),
        per_zone=per_zone,
        projected_tco2e=float(projected),
        verified_tco2e=float(verified),
        constants=_constants(),
    )
