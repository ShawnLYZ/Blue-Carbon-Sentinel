"""Early warning (N5): sub-canopy stress before visible canopy change, with per-zone persistence."""

from __future__ import annotations

from bcs_gs.core.config import Settings
from bcs_gs.fusion.bands import default_settings

EARLY_WARNING_REASON = "Sub-canopy stress — not yet visible from orbit"  # spec §16 wording (alert, task reason)


class EarlyWarning:
    def __init__(self, cfg: Settings | None = None) -> None:
        self._ew = (cfg or default_settings()).risk.early_warning
        self._streak: dict[str, int] = {}
        self._fired: dict[str, bool] = {}

    def observe(
        self, zone_id: str, vegetation: float | None, composite: float | None, investigation: bool
    ) -> bool:
        """True exactly on the Nth consecutive true evaluation of a streak; a false or None resets."""
        ew = self._ew
        if (
            vegetation is None
            or composite is None
            or not (vegetation < ew["vegetation_below"] and composite >= ew["composite_min"])
        ):
            self._streak[zone_id] = 0
            self._fired[zone_id] = False
            return False
        n = self._streak.get(zone_id, 0) + 1
        self._streak[zone_id] = n
        need = ew["persistence_investigation"] if investigation else ew["persistence_baseline"]
        if n >= need and not self._fired.get(zone_id, False):
            self._fired[zone_id] = True
            return True
        return False
