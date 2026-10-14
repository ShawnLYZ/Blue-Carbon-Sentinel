"""Per-zone metrics of a classified site raster against the baseline (addendum N11, H2; spec section 9).

Zones are the 5 x 5 blocks of the 512 x 512 site raster: each pixel centre (u + 0.5, v + 0.5) is
mapped through ``SiteRegistry.raster_to_metres`` and ``zone_at`` (addendum F4). The resulting
label image is computed once per registry and raster size, and every statistic is a bincount
over it.

Null semantics: without canopy pixels in a zone the VARI statistics are ``None``; without a
baseline ``canopy_loss_pp``, ``vari_drop`` and ``discolouration`` are ``None`` (``discolouration``
also when the zone had no baseline water, ``vari_drop`` when either side has no canopy);
``dieback_pct`` and ``new_growth_pct`` are 0 when undefined.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field

import cv2
import numpy as np

from bcs_gs.api.models import ZoneMetrics
from bcs_gs.core.config import Classification, Thresholds
from bcs_gs.site.registry import SiteRegistry
from bcs_gs.vegetation.classify import CANOPY, MUD, OTHER, WATER, classify_raster, hsv, otsu_threshold, rules
from bcs_gs.vegetation.indices import brownness, exg, vari

Cfg = Thresholds | Classification


class ZoneMetricsRow(ZoneMetrics):
    """One ``zone_metrics`` row (addendum H2). ``capture_id`` may be filled by the caller."""

    capture_id: str | None = None

    def to_row(self, capture_id: str | None = None) -> dict[str, object]:
        """The row as a dict keyed exactly by the ``zone_metrics`` columns, for ``Repo``."""
        row = self.model_dump()
        row["capture_id"] = capture_id or self.capture_id
        if row["capture_id"] is None:
            raise ValueError("zone_metrics row needs a capture_id")
        return row


@dataclass(frozen=True)
class BaselineRef:
    """What later captures are compared with, taken from the baseline capture.

    ``exg_threshold`` is the canopy ExG threshold for every capture after the baseline.
    The per-zone dicts are keyed by zone ID; ``None`` where the baseline zone had no canopy
    (VARI) or no water (discolouration).
    """

    canopy_mask: np.ndarray  # bool, raster shape
    water_mask: np.ndarray  # bool, raster shape
    exg_threshold: float
    vari_mean: dict[str, float | None] = field(default_factory=dict)
    vari_p10: dict[str, float | None] = field(default_factory=dict)
    discolouration: dict[str, float | None] = field(default_factory=dict)


# ---- zone label image ---------------------------------------------------------------------------
_LABEL_CACHE: weakref.WeakKeyDictionary[SiteRegistry, dict[int, tuple[np.ndarray, tuple[str, ...]]]] = (
    weakref.WeakKeyDictionary()
)


def zone_index_image(registry: SiteRegistry, size: int = 512) -> tuple[np.ndarray, tuple[str, ...]]:
    """(labels, ids): ``labels[v, u]`` indexes ``ids`` (registry zone order) for every raster pixel.

    Zones are axis-aligned blocks, so the column of each ``u`` and the row of each ``v`` are
    looked up once through the registry and combined. Cached; treat the result as read-only.
    """
    per_registry = _LABEL_CACHE.setdefault(registry, {})
    if size not in per_registry:
        zones = registry.zones()
        index = {(z.col, z.row): i for i, z in enumerate(zones)}
        centres = np.arange(size) + 0.5
        cols = [
            registry.zone(registry.zone_at(registry.raster_to_metres(c, 0.5)[0], 0.0)).col for c in centres
        ]
        rows = [
            registry.zone(registry.zone_at(0.0, registry.raster_to_metres(0.5, c)[1])).row for c in centres
        ]
        grid = np.full((max(rows) + 1, max(cols) + 1), -1, np.intp)
        for (c, r), i in index.items():
            grid[r, c] = i
        labels = grid[np.asarray(rows)[:, None], np.asarray(cols)[None, :]]
        labels.setflags(write=False)
        per_registry[size] = (labels, tuple(z.id for z in zones))
    return per_registry[size]


# ---- vectorised per-zone statistics -------------------------------------------------------------
def _per_zone_mean(labels: np.ndarray, mask: np.ndarray, values: np.ndarray, nz: int) -> list[float | None]:
    lab = labels[mask]
    n = np.bincount(lab, minlength=nz)
    s = np.bincount(lab, weights=values[mask].astype(np.float64), minlength=nz)
    return [float(s[i] / n[i]) if n[i] else None for i in range(nz)]


def _per_zone_quantiles(
    labels: np.ndarray, mask: np.ndarray, values: np.ndarray, nz: int, qs: tuple[float, ...]
) -> list[list[float | None]]:
    """Linear-interpolated quantiles (as ``np.percentile``) of ``values`` in ``mask``, per zone.

    Values must lie in [-1, 1]: one sort of ``label * 4 + value`` groups them by zone in order.
    """
    lab = labels[mask]
    n = np.bincount(lab, minlength=nz)
    keyed = np.sort(lab * 4.0 + values[mask].astype(np.float64))
    start = np.concatenate(([0], np.cumsum(n)[:-1]))
    out: list[list[float | None]] = []
    for q in qs:
        pos = q * np.maximum(n - 1, 0)
        lo = np.floor(pos).astype(np.intp)
        hi = np.minimum(lo + 1, np.maximum(n - 1, 0))
        frac = pos - lo
        res: list[float | None] = []
        for i in range(nz):
            if n[i] == 0:
                res.append(None)
                continue
            a = keyed[start[i] + lo[i]] - 4.0 * i
            b = keyed[start[i] + hi[i]] - 4.0 * i
            res.append(float(a + frac[i] * (b - a)))
        out.append(res)
    return out


def _canopy_vari_stats(
    labels: np.ndarray, canopy: np.ndarray, vari_img: np.ndarray, nz: int, qs: tuple[float, ...]
) -> tuple[list[float | None], list[list[float | None]]]:
    return _per_zone_mean(labels, canopy, vari_img, nz), _per_zone_quantiles(labels, canopy, vari_img, nz, qs)


def _check(rgb: np.ndarray, classes: np.ndarray | None = None) -> None:
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[0] != rgb.shape[1]:
        raise ValueError("expected a square H x W x 3 uint8 RGB site raster")
    if classes is not None and (classes.shape != rgb.shape[:2] or int(classes.max(initial=0)) > OTHER):
        raise ValueError("class map must match the raster shape and hold codes 0-4")


# ---- baseline -----------------------------------------------------------------------------------
def baseline_ref_from(rgb: np.ndarray, cfg: Cfg, *, registry: SiteRegistry) -> BaselineRef:
    """Build the comparison reference from the baseline capture's site raster.

    The ExG threshold is the Otsu threshold of the baseline's ExG, never below the configured
    pre-baseline default, so a baseline without vegetation cannot push brown mud into canopy.
    """
    _check(rgb)
    r = rules(cfg)
    t = max(otsu_threshold(exg(rgb)), r.canopy.exg_default)
    classes = classify_raster(rgb, t, cfg)
    labels, ids = zone_index_image(registry, rgb.shape[0])
    nz = len(ids)
    canopy, water = classes == CANOPY, classes == WATER
    mean, (p10,) = _canopy_vari_stats(labels, canopy, vari(rgb), nz, (0.10,))
    disc = _per_zone_mean(labels, water, brownness(rgb), nz)
    return BaselineRef(
        canopy_mask=canopy,
        water_mask=water,
        exg_threshold=float(t),
        vari_mean=dict(zip(ids, mean, strict=True)),
        vari_p10=dict(zip(ids, p10, strict=True)),
        discolouration=dict(zip(ids, disc, strict=True)),
    )


# ---- zone metrics -------------------------------------------------------------------------------
def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def zone_metrics(
    rgb: np.ndarray, classes: np.ndarray, baseline: BaselineRef | None, cfg: Cfg, *, registry: SiteRegistry
) -> dict[str, ZoneMetricsRow]:
    """Metrics for every zone, keyed by zone ID, with empty ``flags`` (see ``evaluate_flags``)."""
    _check(rgb, classes)
    r = rules(cfg)
    labels, ids = zone_index_image(registry, rgb.shape[0])
    nz = len(ids)
    flat = labels.ravel()
    counts = np.bincount(flat * 5 + classes.ravel().astype(np.intp), minlength=nz * 5).reshape(nz, 5)
    totals = counts.sum(axis=1).astype(np.float64)
    pct = counts / totals[:, None] * 100.0

    vari_img = vari(rgb)
    canopy = classes == CANOPY
    v_mean, (v_p10, v_p90) = _canopy_vari_stats(labels, canopy, vari_img, nz, (0.10, 0.90))

    canopy_loss: list[float | None] = [None] * nz
    vari_drop: list[float | None] = [None] * nz
    discolour: list[float | None] = [None] * nz
    dieback = np.zeros(nz)
    new_growth = np.zeros(nz)
    if baseline is not None:
        if baseline.canopy_mask.shape != classes.shape or baseline.water_mask.shape != classes.shape:
            raise ValueError("baseline masks and raster differ in shape")
        base_canopy_n = np.bincount(labels[baseline.canopy_mask], minlength=nz).astype(np.float64)
        base_pct = base_canopy_n / totals * 100.0
        canopy_loss = [float(base_pct[i] - pct[i, CANOPY]) for i in range(nz)]
        vari_drop = [_sub(baseline.vari_mean.get(z), v_mean[i]) for i, z in enumerate(ids)]

        # Dieback: baseline-canopy pixels now yellow/brown in hue, or still canopy with VARI below
        # the zone's baseline p10 - margin (a cleared pixel is canopy loss, not a low index).
        d = r.dieback
        h, _, _ = hsv(rgb)
        p10 = np.array([np.nan if baseline.vari_p10.get(z) is None else baseline.vari_p10[z] for z in ids])
        low_vari = canopy & (vari_img < (p10 - d.vari_margin)[labels])
        dead = baseline.canopy_mask & (((h >= d.hue_min) & (h <= d.hue_max)) | low_vari)
        dead_n = np.bincount(labels[dead], minlength=nz)
        dieback = np.divide(dead_n * 100.0, base_canopy_n, out=np.zeros(nz), where=base_canopy_n > 0)

        # New growth: canopy outside the dilated baseline canopy, in components of min-max px.
        g = r.new_growth
        k = 2 * g.mask_dilate_px + 1
        grown_base = cv2.dilate(
            baseline.canopy_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        )
        fresh = (canopy & (grown_base == 0)).astype(np.uint8)
        _, cc, stats, _ = cv2.connectedComponentsWithStats(fresh, connectivity=8)
        areas = stats[:, cv2.CC_STAT_AREA]
        keep = (areas >= g.component_min_px) & (areas <= g.component_max_px)
        keep[0] = False  # background component
        new_n = np.bincount(labels[keep[cc]], minlength=nz)
        new_growth = new_n * 100.0 / totals

        # Discolouration over the baseline water mask (turbid water reclassifies as mud).
        now_disc = _per_zone_mean(labels, baseline.water_mask, brownness(rgb), nz)
        discolour = [_sub(now_disc[i], baseline.discolouration.get(z)) for i, z in enumerate(ids)]

    return {
        z: ZoneMetricsRow(
            zone_id=z,
            canopy_pct=float(pct[i, CANOPY]),
            water_pct=float(pct[i, WATER]),
            mud_pct=float(pct[i, MUD]),
            other_pct=float(pct[i, OTHER]),
            vari_mean=v_mean[i],
            vari_p10=v_p10[i],
            vari_p90=v_p90[i],
            canopy_loss_pp=canopy_loss[i],
            vari_drop=vari_drop[i],
            dieback_pct=float(dieback[i]),
            new_growth_pct=float(new_growth[i]),
            discolouration=discolour[i],
        )
        for i, z in enumerate(ids)
    }
