"""J1 frame codec: byte layout and round trip. Generated arrays and opaque bytes only."""

from __future__ import annotations

import json

import numpy as np
import pytest
from bcs_gs.live.codec import decode_frame, encode_frame


def _height() -> np.ndarray:
    return np.arange(256 * 256, dtype=np.uint16).reshape(256, 256)


def test_codec_round_trip_and_layout():
    h = _height()
    buf = encode_frame({"seq": 3, "mode": "depth"}, b"JPEGBYTES", h)
    assert buf[:4] == b"BCSL"
    assert int.from_bytes(buf[4:6], "little") == 1
    assert int.from_bytes(buf[6:8], "little") == 0b11
    n = int.from_bytes(buf[8:12], "little")
    assert json.loads(buf[12 : 12 + n])["seq"] == 3
    assert buf[12 + n : 12 + n + 9] == b"JPEGBYTES"
    assert len(buf) == 12 + n + 9 + 131072
    header, jpg, h2 = decode_frame(buf)
    assert header["raster_bytes"] == 9 and header["height_bytes"] == 131072
    assert jpg == b"JPEGBYTES" and (h2 == h).all() and h2.dtype == np.uint16


def test_height_is_little_endian_row_major():
    h = np.zeros((256, 256), np.uint16)
    h[0, 1] = 0x0102
    h[1, 0] = 0x0304
    buf = encode_frame({}, None, h)
    body = buf[12 + int.from_bytes(buf[8:12], "little") :]
    assert body[:4] == bytes([0, 0, 0x02, 0x01])  # row 0, columns 0 and 1
    assert body[512:514] == bytes([0x04, 0x03])  # row 1 starts after 256 * 2 bytes


@pytest.mark.parametrize(
    ("jpeg", "height", "flags"), [(b"x", None, 1), (None, True, 2), (None, None, 0), (b"x", True, 3)]
)
def test_flags_follow_presence(jpeg, height, flags):
    buf = encode_frame({}, jpeg, _height() if height else None)
    assert int.from_bytes(buf[6:8], "little") == flags
    header, jpg, h = decode_frame(buf)
    assert (jpg is not None) == bool(flags & 1) and (h is not None) == bool(flags & 2)
    assert header["raster_bytes"] == (1 if jpeg else 0)
    assert header["height_bytes"] == (131072 if height else 0)


def test_encode_rejects_wrong_height_shape():
    with pytest.raises(ValueError):
        encode_frame({}, None, np.zeros((10, 10), np.uint16))


@pytest.mark.parametrize("bad", [b"", b"BCSL", b"XXXX" + bytes(20)])
def test_decode_rejects_malformed(bad):
    with pytest.raises(ValueError):
        decode_frame(bad)


def test_decode_rejects_truncated_and_bad_version():
    buf = encode_frame({}, b"abc", _height())
    with pytest.raises(ValueError):
        decode_frame(buf[:-1])
    with pytest.raises(ValueError):
        decode_frame(buf[:4] + (2).to_bytes(2, "little") + buf[6:])
