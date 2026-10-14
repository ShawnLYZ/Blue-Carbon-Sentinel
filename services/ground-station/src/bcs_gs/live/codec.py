"""J1 frame codec.

Layout: ``BCSL`` | version u16 LE (1) | flags u16 LE (bit 0 raster, bit 1 height) | header length
u32 LE | header JSON (UTF-8) | raster JPEG | height map (256 x 256 u16 LE, row-major, row 0 north).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

MAGIC = b"BCSL"
VERSION = 1
FLAG_RASTER = 0b01
FLAG_HEIGHT = 0b10
HEIGHT_W = HEIGHT_H = 256
HEIGHT_BYTES = HEIGHT_W * HEIGHT_H * 2
_PREFIX = 12


def encode_frame(header: dict[str, Any], raster_jpeg: bytes | None, height_u16: np.ndarray | None) -> bytes:
    """Build one message. ``raster_bytes`` and ``height_bytes`` are set from the payloads given."""
    flags = 0
    parts: list[bytes] = []
    if raster_jpeg is not None:
        flags |= FLAG_RASTER
        parts.append(bytes(raster_jpeg))
    if height_u16 is not None:
        if height_u16.shape != (HEIGHT_H, HEIGHT_W):
            raise ValueError(f"height map must be {HEIGHT_H}x{HEIGHT_W}, got {height_u16.shape}")
        flags |= FLAG_HEIGHT
        parts.append(np.ascontiguousarray(height_u16).astype("<u2", copy=False).tobytes())
    head = {
        **header,
        "raster_bytes": len(raster_jpeg) if raster_jpeg is not None else 0,
        "height_bytes": HEIGHT_BYTES if height_u16 is not None else 0,
    }
    raw = json.dumps(head, separators=(",", ":")).encode("utf-8")
    prefix = (
        MAGIC + VERSION.to_bytes(2, "little") + flags.to_bytes(2, "little") + len(raw).to_bytes(4, "little")
    )
    return b"".join([prefix, raw, *parts])


def decode_frame(buf: bytes) -> tuple[dict[str, Any], bytes | None, np.ndarray | None]:
    """Parse one message; raises ``ValueError`` on anything malformed."""
    if len(buf) < _PREFIX or buf[:4] != MAGIC:
        raise ValueError("not a BCSL frame")
    if int.from_bytes(buf[4:6], "little") != VERSION:
        raise ValueError("unsupported BCSL version")
    flags = int.from_bytes(buf[6:8], "little")
    n = int.from_bytes(buf[8:12], "little")
    if len(buf) < _PREFIX + n:
        raise ValueError("truncated header")
    try:
        header = json.loads(buf[_PREFIX : _PREFIX + n].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("bad header JSON") from exc
    if not isinstance(header, dict):
        raise ValueError("header is not an object")  # noqa: TRY004
    pos = _PREFIX + n
    jpeg: bytes | None = None
    height: np.ndarray | None = None
    if flags & FLAG_RASTER:
        r = int(header.get("raster_bytes", -1))
        if r < 0 or pos + r > len(buf):
            raise ValueError("truncated raster")
        jpeg, pos = bytes(buf[pos : pos + r]), pos + r
    if flags & FLAG_HEIGHT:
        if int(header.get("height_bytes", -1)) != HEIGHT_BYTES or pos + HEIGHT_BYTES > len(buf):
            raise ValueError("truncated height map")
        raw = np.frombuffer(buf, dtype="<u2", count=HEIGHT_W * HEIGHT_H, offset=pos)
        height = raw.reshape(HEIGHT_H, HEIGHT_W).astype(np.uint16)
        pos += HEIGHT_BYTES
    if pos != len(buf):
        raise ValueError("trailing bytes")
    return header, jpeg, height
