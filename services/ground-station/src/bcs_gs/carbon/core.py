"""Carbon arithmetic (pure). Constants are cited in config/carbon.yaml (M6)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

C_TO_CO2E = 44 / 12


def _get(row: Any, key: str) -> float:
    return float(row[key] if isinstance(row, dict) else getattr(row, key))


def stock_tco2e(canopy_fraction: float, area_ha: float, density: float) -> float:
    """Carbon stock in tCO2e: fraction x area x density (Mg C/ha) x 44/12."""
    return canopy_fraction * area_ha * density * C_TO_CO2E


def cohort_rate(age_years: int, rates: Sequence[Any]) -> float:
    """Sequestration rate (Mg C/ha/yr) for a cohort age; ages past the last band use the last rate."""
    if not rates:
        return 0.0
    for r in rates:
        if _get(r, "min_age") <= age_years <= _get(r, "max_age"):
            return _get(r, "rate")
    return _get(rates[-1], "rate") if age_years > _get(rates[-1], "max_age") else 0.0


def cohort_sequestration_tco2e(
    age_years: int, area_ha: float, survival: float, rates: Sequence[Any]
) -> float:
    """tCO2e sequestered in one year by a planted cohort of the given age."""
    return cohort_rate(age_years, rates) * area_ha * survival * C_TO_CO2E
