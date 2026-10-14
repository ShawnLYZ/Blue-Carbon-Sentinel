"""Zone flags from zone metrics (product spec section 9 thresholds; kinds from addendum F5).

A flag fires when its value reaches the threshold (>=). A ``None`` value never fires.
Flags are returned in a fixed order: canopy_loss, dieback, index_drop, discolouration, new_growth.
"""

from __future__ import annotations

from bcs_gs.api.models import ZoneFlag, ZoneMetrics
from bcs_gs.core.config import FlagThresholds, Thresholds


def evaluate_flags(
    metrics: ZoneMetrics, at_application: ZoneMetrics | None, cfg: Thresholds | FlagThresholds
) -> list[ZoneFlag]:
    """Flags for one zone; ``at_application`` is the zone's metrics in the capture at plan application."""
    t = cfg.flags if isinstance(cfg, Thresholds) else cfg
    checks = (
        ("canopy_loss", metrics.canopy_loss_pp, t.canopy_loss_pp),
        ("dieback", metrics.dieback_pct, t.dieback_pct),
        ("index_drop", metrics.vari_drop, t.index_drop),
        ("discolouration", metrics.discolouration, t.discolouration),
    )
    out = [ZoneFlag(kind=k, value=v, threshold=th) for k, v, th in checks if v is not None and v >= th]
    if metrics.new_growth_pct is not None and metrics.new_growth_pct >= t.new_growth_pct:
        out.append(ZoneFlag(kind="new_growth", value=metrics.new_growth_pct, threshold=t.new_growth_pct))
    elif at_application is not None:
        gain = metrics.canopy_pct - at_application.canopy_pct
        if gain >= t.new_growth_canopy_pp:
            out.append(ZoneFlag(kind="new_growth", value=gain, threshold=t.new_growth_canopy_pp))
    return out
