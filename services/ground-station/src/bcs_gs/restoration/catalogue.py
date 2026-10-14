"""The restoration catalogue constraints (product spec section 20, M5 Global Constraints). Pure.

* Planting (*Rhizophora* or *Avicennia*) needs mud (>= 2 % of the zone) or an eroded edge; otherwise the
  item is rejected with 422 "planting needs mud or an eroded edge in <zone>" (or, for an AI draft,
  ``drop_invalid=True``, the planting is dropped with a warning).
* *Rhizophora* where porewater is above 40 PSU is switched to *Avicennia* with a warning.
* ``planted_area_ha`` defaults to ``sapling_count`` / 4,400.
* Sapling density is at most 4,400 per ha (``sapling_count`` <= 4,400 x ``planted_area_ha``, no negative
  counts or areas), on operator edits and AI drafts alike; otherwise 422 "sapling density exceeds 4400 per
  ha in <zone>" (an AI draft drops the planting with a warning).
* The planted area of a zone, summed over every planting intervention of its item(s), is at most 1 ha
  (the zone's size); otherwise 422 "planted area exceeds 1 ha in <zone>" (an AI draft drops the planting
  that would exceed it, with a warning; ruling R30).

An eroded edge (``is_eroded``): the zone's latest forecast ``without`` series shows land L falling by
>= 0.02 by 2035, or the zone has water >= 5 % next to mud (water >= 5 % and mud > 0 in the zone).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from bcs_gs.api.errors import ApiError
from bcs_gs.api.models import PlanItem

DENSITY_PER_HA = 4400
MIN_MUD = 0.02  # fraction of the zone
ERODED_WATER = 0.05  # fraction of the zone
ERODED_LAND_DROP = 0.02  # L, 2026 -> 2035, in the "without" scenario
AVICENNIA_ABOVE_PSU = 40.0
PLANT_KINDS = ("plant_rhizophora", "plant_avicennia")
SWITCH_WARNING = "switched to Avicennia marina: porewater > 40 PSU"
MAX_PLANTED_HA = 1.0  # a zone is 1 ha
EPS = 1e-9


@dataclass(frozen=True)
class ZonePlanState:
    mud: float = 0.0  # fraction of the zone, latest evidence-grade capture
    porewater_psu: float | None = None  # the zone's covering-node porewater salinity (max stress)
    eroded: bool = False


def is_eroded(water: float, mud: float, land_without: Sequence[float] | None) -> bool:
    """Water >= 5 % next to mud, or L falling by >= 0.02 over the forecast's ``without`` series."""
    if water >= ERODED_WATER and mud > 0:
        return True
    return bool(land_without) and land_without[0] - land_without[-1] >= ERODED_LAND_DROP - EPS


def planting_error(zone_id: str) -> str:
    return f"planting needs mud or an eroded edge in {zone_id}"


def area_error(zone_id: str) -> str:
    return f"planted area exceeds 1 ha in {zone_id}"


def density_error(zone_id: str) -> str:
    return f"sapling density exceeds {DENSITY_PER_HA} per ha in {zone_id}"


def validate_items(
    items: Sequence[PlanItem], zone_states: Mapping[str, ZonePlanState], *, drop_invalid: bool = False
) -> tuple[list[PlanItem], list[str]]:
    """(normalised items, warnings). A zone without a state has no mud and no eroded edge."""
    out: list[PlanItem] = []
    warnings: list[str] = []
    planted: dict[str, float] = {}  # zone -> planted area so far (ha)
    for item in items:
        st = zone_states.get(item.zone_id) or ZonePlanState()
        ivs = []
        for iv in item.interventions:
            if iv.kind in PLANT_KINDS:
                if st.mud < MIN_MUD - EPS and not st.eroded:
                    if not drop_invalid:
                        raise ApiError("validation_error", 422, planting_error(item.zone_id))
                    warnings.append(f"dropped {iv.kind} in {item.zone_id}: {planting_error(item.zone_id)}")
                    continue
                n = iv.sapling_count or 0  # the density the AI path enforces in RestorationPlanner.check
                if n < 0 or (iv.planted_area_ha or 0.0) < 0 or (
                    iv.planted_area_ha is not None and n > DENSITY_PER_HA * iv.planted_area_ha + EPS
                ):
                    if not drop_invalid:
                        raise ApiError("validation_error", 422, density_error(item.zone_id))
                    warnings.append(f"dropped {iv.kind} in {item.zone_id}: {density_error(item.zone_id)}")
                    continue
                kind = iv.kind
                if (
                    kind == "plant_rhizophora"
                    and st.porewater_psu is not None
                    and st.porewater_psu > AVICENNIA_ABOVE_PSU
                ):
                    kind = "plant_avicennia"
                    warnings.append(SWITCH_WARNING)
                area = iv.planted_area_ha
                if area is None and iv.sapling_count is not None:
                    area = iv.sapling_count / DENSITY_PER_HA
                total = planted.get(item.zone_id, 0.0) + (area or 0.0)
                if total > MAX_PLANTED_HA + EPS:
                    if not drop_invalid:
                        raise ApiError("validation_error", 422, area_error(item.zone_id))
                    warnings.append(f"dropped {iv.kind} in {item.zone_id}: {area_error(item.zone_id)}")
                    continue
                planted[item.zone_id] = total
                iv = iv.model_copy(update={"kind": kind, "planted_area_ha": area})
            ivs.append(iv)
        if ivs or not drop_invalid:  # an AI item left with nothing is dropped
            out.append(item.model_copy(update={"interventions": ivs}))
    return out, warnings
