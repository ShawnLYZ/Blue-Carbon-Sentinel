"""Code-only repaint of the real site raster for a forecast year (pure NumPy, OpenCV for dilation).

Every pixel outside a changed zone keeps the real capture. All pixel choices are deterministic: the
canopy-loss and sapling pixels come from a fixed multiplicative hash of the pixel index (never the
randomised builtin ``hash()``), so the same inputs give the same image.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

CANOPY, WATER, MUD, OTHER = 1, 2, 3, 4  # class codes (F5)
DIEBACK_COLOUR = (120, 100, 80)
TURBID_COLOUR = (140, 110, 70)
SAPLING_COLOUR = (60, 140, 60)
TURBIDITY_TINT = 0.6
DEFAULT_MUD = (139, 101, 60)  # classes.png palette, for a scene without mud / water pixels
DEFAULT_WATER = (30, 100, 200)
_SALT_LOSS, _SALT_SAPLING = 0x9E3779B9, 0x85EBCA6B  # fixed salts, distinct per use
_MASK32 = 0xFFFFFFFF


@dataclass(frozen=True)
class ZoneChange:
    """One zone's change from the real capture to a forecast year; every field is 0-1
    (``eroded_strip_m`` is in metres)."""

    dieback_frac: float = 0.0
    canopy_loss_frac: float = 0.0
    eroded_strip_m: float = 0.0
    turbidity_stress: float = 0.0
    sapling_fill: float = 0.0

    def is_zero(self) -> bool:
        return not any((
            self.dieback_frac, self.canopy_loss_frac, self.eroded_strip_m,
            self.turbidity_stress, self.sapling_fill,
        ))  # fmt: skip


@dataclass(frozen=True)
class ZoneGrid:
    """The zone label image of the raster (as the M2 zone metrics use it) and the ground resolution."""

    labels: np.ndarray  # intp, labels[v, u] indexes ids
    ids: tuple[str, ...]
    m_per_px: float

    def mask(self, zone_id: str) -> np.ndarray:
        return self.labels == self.ids.index(zone_id)


def _hash01(shape: tuple[int, int], salt: int) -> np.ndarray:
    """Per-pixel fixed hash of the pixel index (a 32-bit murmur-style finalizer), in [0, 1)."""
    x = (np.arange(shape[0] * shape[1], dtype=np.uint64) + np.uint64(salt)) & np.uint64(_MASK32)
    for shift, mult in ((16, 0x85EBCA6B), (13, 0xC2B2AE35), (16, 1)):
        x ^= x >> np.uint64(shift)
        x = (x * np.uint64(mult)) & np.uint64(_MASK32)
    return (x / float(_MASK32 + 1)).reshape(shape)


def strip_px(change: ZoneChange, grid: ZoneGrid) -> int:
    return round(change.eroded_strip_m / grid.m_per_px) if change.eroded_strip_m > 0 else 0


def eroded_mask(classes: np.ndarray, zone: np.ndarray, px: int) -> np.ndarray:
    """Land pixels of the zone within ``px`` pixels of water: the strip along the water edge. Water edges
    are found by dilating the water mask and intersecting it with the land."""
    if px <= 0:
        return np.zeros(classes.shape, bool)
    water = (classes == WATER).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
    near = cv2.dilate(water, k).astype(bool)
    return near & zone & (classes != WATER) & (classes != 0)


def _mean_colour(img: np.ndarray, mask: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    return img[mask].astype(np.float64).mean(axis=0) if mask.any() else fallback


def _blend(out: np.ndarray, mask: np.ndarray, colour: object, w: float) -> None:
    if mask.any() and w > 0:
        out[mask] = out[mask] * (1.0 - w) + np.asarray(colour, np.float64) * w


def repaint(
    raster_rgb: np.ndarray, classes: np.ndarray, zone_changes: dict[str, ZoneChange], *, grid: ZoneGrid
) -> np.ndarray:
    """A new H x W x 3 uint8 image: ``raster_rgb`` with each changed zone repainted."""
    if raster_rgb.shape[:2] != classes.shape or classes.shape != grid.labels.shape:
        raise ValueError("raster, class map and zone grid must have the same shape")
    out = raster_rgb.astype(np.float64)
    loss_rank = _hash01(classes.shape, _SALT_LOSS)
    sapling_rank = _hash01(classes.shape, _SALT_SAPLING)
    all_mud = _mean_colour(raster_rgb, classes == MUD, np.asarray(DEFAULT_MUD, np.float64))
    all_water = _mean_colour(raster_rgb, classes == WATER, np.asarray(DEFAULT_WATER, np.float64))
    for zone_id, ch in sorted(zone_changes.items()):
        if ch.is_zero() or zone_id not in grid.ids:
            continue
        zone = grid.mask(zone_id)
        canopy, mud, water = zone & (classes == CANOPY), zone & (classes == MUD), zone & (classes == WATER)
        mud_colour = _mean_colour(raster_rgb, mud, all_mud)
        water_colour = _mean_colour(raster_rgb, water, all_water)
        _blend(out, canopy, DIEBACK_COLOUR, float(np.clip(ch.dieback_frac, 0, 1)))
        n_lost = round(canopy.sum() * float(np.clip(ch.canopy_loss_frac, 0, 1)))
        if n_lost:
            ys, xs = np.nonzero(canopy)
            order = np.argsort(loss_rank[ys, xs], kind="stable")[:n_lost]  # deterministic hash order
            out[ys[order], xs[order]] = mud_colour
        eroded = eroded_mask(classes, zone, strip_px(ch, grid))
        out[eroded] = water_colour
        _blend(out, water | eroded, TURBID_COLOUR, TURBIDITY_TINT * float(np.clip(ch.turbidity_stress, 0, 1)))
        if ch.sapling_fill > 0:
            speckle = mud & ~eroded & (sapling_rank < float(np.clip(ch.sapling_fill, 0, 1)))
            out[speckle] = SAPLING_COLOUR
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)
