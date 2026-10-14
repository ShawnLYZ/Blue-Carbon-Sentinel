"""Capture artefacts under the H5 storage keys: image.jpg, height.png, classes.png, ndvi.png."""

from __future__ import annotations

import struct
import zlib
from datetime import datetime
from typing import Any

import cv2
import numpy as np

from bcs_gs.store.media import MediaStore

BUCKET = "captures"
JPEG_QUALITY = 85
FILES = {"image": "image.jpg", "height": "height.png", "classes": "classes.png", "ndvi": "ndvi.png"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# classes.png palette, index = class code (F5): 0 unclassified, 1 canopy, 2 water, 3 mud, 4 other.
CLASS_PALETTE: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),
    (34, 139, 34),
    (30, 100, 200),
    (139, 101, 60),
    (170, 170, 170),
)
CONTENT_TYPES = {"image": "image/jpeg", "height": "image/png", "classes": "image/png", "ndvi": "image/png"}


def media_keys(capture_id: str, taken_at: datetime) -> dict[str, str]:
    prefix = f"{taken_at:%Y}/{taken_at:%m}/{taken_at:%d}/{capture_id}"
    return {kind: f"{prefix}/{name}" for kind, name in FILES.items()}


def vari_to_u16(vari_img: np.ndarray) -> np.ndarray:
    """VARI [-1, 1] -> 0-65535 (H5)."""
    v = np.clip(np.asarray(vari_img, np.float64), -1.0, 1.0)
    return np.rint((v + 1.0) * 0.5 * 65535.0).astype(np.uint16)


def _encode(ext: str, img: np.ndarray, params: list[int] | None = None) -> bytes:
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        raise RuntimeError(f"could not encode {ext}")
    return buf.tobytes()


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def indexed_png(codes: np.ndarray, palette: tuple[tuple[int, int, int], ...] = CLASS_PALETTE) -> bytes:
    """8-bit indexed (palette, colour type 3) PNG whose pixel values are ``codes`` (H5 classes.png).
    OpenCV writes no palette PNGs, so the chunks are written here (filter type 0 on every row)."""
    img = np.ascontiguousarray(codes, np.uint8)
    if img.ndim != 2 or int(img.max(initial=0)) >= len(palette):
        raise ValueError("class codes must be a 2-D array of palette indices")
    h, w = img.shape
    raw = np.hstack([np.zeros((h, 1), np.uint8), img]).tobytes()  # leading filter byte per row
    return b"".join((
        PNG_SIGNATURE,
        _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)),
        _chunk(b"PLTE", bytes(c for rgb in palette for c in rgb)),
        _chunk(b"IDAT", zlib.compress(raw, 1)),
        _chunk(b"IEND", b""),
    ))  # fmt: skip


def encode_artefacts(
    rgb: np.ndarray, height_u16: np.ndarray, classes: np.ndarray, vari_img: np.ndarray
) -> dict[str, bytes]:
    bgr = cv2.cvtColor(np.ascontiguousarray(rgb[..., :3], np.uint8), cv2.COLOR_RGB2BGR)
    return {
        "image": _encode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]),
        "height": _encode(".png", np.ascontiguousarray(height_u16, np.uint16)),
        "classes": indexed_png(classes),  # palette PNG, pixel value = class code (F5)
        "ndvi": _encode(".png", vari_to_u16(vari_img)),
    }


def write_artefacts(
    media: MediaStore,
    capture_id: str,
    taken_at: datetime,
    raster: Any,
    height_u16: np.ndarray,
    classes: np.ndarray,
    vari: np.ndarray,
    cloud: bool,
    *,
    protected: bool = False,
) -> dict[str, str]:
    """Write the four artefacts locally (queued for upload when ``cloud``); returns kind -> key."""
    rgb = getattr(raster, "image", raster)
    keys = media_keys(capture_id, taken_at)
    for kind, data in encode_artefacts(rgb, height_u16, classes, vari).items():
        media.put(BUCKET, keys[kind], data, CONTENT_TYPES[kind], protected=protected, cloud=cloud)
    return keys


def decode_indexed_png(data: bytes) -> np.ndarray:
    """The class codes of an 8-bit indexed PNG written by ``indexed_png`` (filter type 0 on every row)."""
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("not a PNG")
    pos, chunks = 8, {}
    while pos + 8 <= len(data):
        (n,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunks[kind] = chunks.get(kind, b"") + data[pos + 8 : pos + 8 + n]
        pos += 12 + n
    w, h, depth, ctype = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    if (depth, ctype) != (8, 3):
        raise ValueError("not an 8-bit indexed PNG")
    raw = np.frombuffer(zlib.decompress(chunks[b"IDAT"]), np.uint8).reshape(h, w + 1)
    if raw[:, 0].any():
        raise ValueError("unsupported PNG row filter")
    return raw[:, 1:].copy()
