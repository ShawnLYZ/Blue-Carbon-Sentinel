"""Which zones a FLUX illustration may touch, and the editing instruction for them (pure).

``changed_zones`` compares the central keyframe of ``year`` with 2026 (ruling R23). A zone counts as
changed when |dC| >= 0.05, the land LOSS L2026 - Ly >= 0.02, the turbidity stress (ruling R10) moves by
>= 0.2, or a planted cohort covers >= 0.1 of the zone; at most the 6 with the highest change score are
kept (ruling R24). Only those zones are described and composited.

``build_instruction`` writes one sentence per changed zone with position words (rows 1-2 north, 3 central,
4-5 south; columns A-B west, C central, D-E east; "central central" is "centre") and always ends with the
fixed suffix of the global constraints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bcs_gs.futures.heights import START_YEAR, TURBIDITY_KEY
from bcs_gs.futures.repaint import ZoneChange

SUFFIX = "Keep everything else identical; top-down view of a handmade clay mangrove model."
_ZONE_RE = re.compile(r"([A-Za-z])(\d+)$")
_NS = {1: "north", 2: "north", 3: "central", 4: "south", 5: "south"}
_EW = {"A": "west", "B": "west", "C": "central", "D": "east", "E": "east"}


@dataclass(frozen=True)
class ChangeThreshold:
    canopy: float = 0.05  # |dC|, fraction of the zone
    land: float = 0.02  # |dL|, fraction of the zone
    turbidity: float = 0.2  # change of the turbidity stress, 0-1
    cohort: float = 0.1  # planted cohort fraction


DEFAULT_THRESHOLD = ChangeThreshold()
MAX_ZONES = 6  # illustrated zones per image (ruling R24)


def _val(b: Any) -> float:
    return float(b["central"] if isinstance(b, dict) else b.central)


def _turbidity(s0: float, sigma0: float, sigma_y: float) -> float:
    return min(1.0, max(0.0, s0 * sigma_y / max(sigma0, 1e-6))) if s0 > 0 else 0.0


def change_scores(
    forecast: dict[str, Any],
    scenario: str,
    year: int,
    threshold: ChangeThreshold = DEFAULT_THRESHOLD,
    *,
    base_state: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Zone ID -> change score for the zones that reach ``threshold`` between 2026 and ``year`` (central
    run). score = max(|dC| / canopy, land loss / land, d turbidity / turbidity, cohort / cohort), so a
    score >= 1 means the zone passes (ruling R24: land LOSS only, L2026 - Ly)."""
    zones = ((forecast.get("keyframes") or {}).get(scenario) or {}).get("zones") or {}
    out: dict[str, float] = {}
    for zone_id, points in zones.items():
        by_year = {int(p["year"]): p for p in points}
        p0, py = by_year.get(START_YEAR), by_year.get(year)
        if p0 is None or py is None or year == START_YEAR:
            continue
        st = (base_state or {}).get(zone_id)
        s0 = float((getattr(st, "stressors", None) or {}).get(TURBIDITY_KEY) or 0.0)
        t0 = _turbidity(s0, _val(p0["sigma"]), _val(p0["sigma"]))
        ty = _turbidity(s0, _val(p0["sigma"]), _val(py["sigma"]))
        score = max(
            abs(_val(py["canopy"]) - _val(p0["canopy"])) / threshold.canopy,
            (_val(p0["land"]) - _val(py["land"])) / threshold.land,
            abs(ty - t0) / threshold.turbidity,
            float(py.get("cohort_fraction") or 0.0) / threshold.cohort,
        )
        if score >= 1.0 - 1e-9:
            out[zone_id] = score
    return out


def changed_zones(
    forecast: dict[str, Any],
    scenario: str,
    year: int,
    threshold: ChangeThreshold = DEFAULT_THRESHOLD,
    *,
    base_state: dict[str, Any] | None = None,
    max_zones: int = MAX_ZONES,
) -> list[str]:
    """Sorted IDs of the illustrated zones: those passing ``threshold`` (``change_scores``), capped at the
    ``max_zones`` highest scores (ties by zone ID; ruling R24). ``base_state`` maps zone ID to an object
    with ``stressors`` (the turbidity stress at 2026)."""
    scores = change_scores(forecast, scenario, year, threshold, base_state=base_state)
    top = sorted(scores, key=lambda z: (-scores[z], z))[:max_zones]
    return sorted(top)


def position_words(zone_id: str) -> str:
    """'KSL-B2' -> 'north-west'; 'KSL-C3' -> 'centre'."""
    m = _ZONE_RE.search(zone_id)
    if m is None:
        return "marked"
    ns = _NS.get(int(m.group(2)), "central")
    ew = _EW.get(m.group(1).upper(), "central")
    return "centre" if ns == ew == "central" else f"{ns}-{ew}"


def _pct(v: float) -> str:
    return f"{round(100 * min(1.0, max(0.0, v)))}%"


def _clauses(ch: ZoneChange) -> list[str]:
    out = []
    if ch.dieback_frac > 0.005:
        out.append(f"about {_pct(ch.dieback_frac)} of the mangrove canopy turns brown-grey with dieback")
    if ch.canopy_loss_frac > 0.005:
        out.append(f"about {_pct(ch.canopy_loss_frac)} of the canopy is gone, leaving bare mud")
    if ch.eroded_strip_m >= 0.5:
        out.append(f"the shoreline is eroded about {round(ch.eroded_strip_m)} m inland")
    if ch.turbidity_stress > 0.005:
        out.append(f"the water is murky and silt-brown ({_pct(ch.turbidity_stress)} turbidity)")
    if ch.sapling_fill > 0.005:
        out.append(f"young mangrove saplings dot about {_pct(ch.sapling_fill)} of the mud")
    return out or ["the mangroves look slightly different"]


def build_instruction(changes: dict[str, ZoneChange], scenario: str, year: int) -> str:
    """One sentence per changed zone (sorted by ID), then the fixed suffix."""
    when = f"By {year} {'with the restoration plan' if scenario == 'with' else 'without intervention'}"
    sentences = []
    for zone_id in sorted(changes):
        where = position_words(zone_id)
        place = "the centre zone" if where == "centre" else f"the {where} zone"
        sentences.append(f"{when}, in {place} {'; '.join(_clauses(changes[zone_id]))}.")
    return " ".join([*sentences, SUFFIX])
