"""``/ws/live`` (addendum J1): latest-frame-wins gateway and the real socket. Generated arrays only."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import numpy as np
from bcs_gs.live.codec import decode_frame
from bcs_gs.reality import HeightFrame
from websockets.asyncio.client import connect

T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)


def frame(seq: int, *, mode: str = "depth") -> HeightFrame:
    rng = np.random.default_rng(seq)
    return HeightFrame(
        seq=seq, frame_seq=100 + seq, captured_at=T0, processed_at=T0 + timedelta(milliseconds=87),
        mode=mode, quality=0.123456,  # type: ignore[arg-type]
        height_u16=rng.integers(0, 65536, (256, 256), dtype=np.uint16),
        raster_rgb=rng.integers(0, 256, (512, 512, 3), dtype=np.uint8),
        calibration_id="cal-1", process_ms=12.0,
    )  # fmt: skip


async def test_slow_client_gets_latest_frame_only(live_gateway_world):
    gw, client = live_gateway_world
    client.block()
    for seq in range(5):
        gw.offer(frame(seq))
    client.unblock()
    got = await client.received()
    assert [f.header["seq"] for f in got] == [0, 4]  # first in flight, then only the newest


async def test_header_fields_and_shared_jpeg(live_gateway_world):
    gw, client = live_gateway_world
    gw.offer(frame(7))
    (got,) = await client.received()
    h = got.header
    assert h["seq"] == 7 and h["frame_seq"] == 107 and h["mode"] == "depth"
    assert h["captured_at"] == "2026-10-16T03:04:05.123Z" and h["processed_at"] == "2026-10-16T03:04:05.210Z"
    assert h["latency_ms"] == 87 and h["quality"] == 0.123 and h["calibration_id"] == "cal-1"
    assert (h["raster_w"], h["raster_h"], h["height_w"], h["height_h"], h["max_relief_m"]) == (
        512, 512, 256, 256, 40,
    )  # fmt: skip
    assert got.jpeg is not None and got.jpeg[:2] == b"\xff\xd8" and h["raster_bytes"] == len(got.jpeg)
    assert (got.height == frame(7).height_u16).all()


async def test_clients_share_one_encode_and_do_not_block_each_other(live_gateway_world):
    gw, slow = live_gateway_world
    fast = await gw.world_add_client()
    gw.configure(fast.handle, {"type": "config", "max_fps": 60})
    slow.block()
    for seq in range(3):
        gw.offer(frame(seq))
        await asyncio.sleep(0.02)
    fast_got = await fast.received()
    assert [f.header["seq"] for f in fast_got] == [0, 1, 2]
    slow.unblock()
    got = await slow.received()
    assert [f.header["seq"] for f in got] == [0, 2]
    assert got[0].jpeg == fast_got[0].jpeg


async def test_max_fps_coalesces_and_toggles_apply(live_gateway_world):
    gw, client = live_gateway_world
    gw.configure(client.handle, {"type": "config", "max_fps": 5, "raster": False, "height": True})
    for seq in range(6):
        gw.offer(frame(seq))
        await asyncio.sleep(0.01)
    got = await client.received()
    assert [f.header["seq"] for f in got] == [0, 5]  # 0 immediately, the newest after 200 ms
    assert all(f.jpeg is None and f.height is not None for f in got)


async def test_invalid_config_is_ignored(live_gateway_world):
    gw, client = live_gateway_world
    for bad in (
        "not a dict", {"type": "nope"}, {"type": "config", "max_fps": "fast"},
        {"type": "config", "max_fps": 0}, {"type": "config", "max_fps": True},
        {"type": "config", "raster": "yes"}, {"type": "config", "max_fps": 1000},
    ):  # fmt: skip
        gw.configure(client.handle, bad)
    gw.offer(frame(1))
    (got,) = await client.received()
    assert got.jpeg is not None and got.height is not None
    assert client.handle.max_fps == 10


async def test_failed_client_is_dropped(live_gateway_world):
    gw, client = live_gateway_world
    assert gw.client_count == 1
    client.fail()
    gw.offer(frame(1))
    await client.received()
    assert gw.client_count == 0


async def test_live_socket_end_to_end(gs):
    gw = gs.services.live
    url = f"ws://127.0.0.1:{gs.port}/ws/live"
    async with connect(url) as ws:
        await ws.send(json.dumps({"type": "config", "max_fps": 30, "raster": True, "height": False}))
        await ws.send("{broken json")  # ignored; the socket stays up
        deadline = time.monotonic() + 5
        while not (gw.client_count == 1 and gw.client_configs() == [(30.0, True, False)]):
            assert time.monotonic() < deadline, "config never applied"
            await asyncio.sleep(0.01)
        gw.loop.call_soon_threadsafe(gw.offer, frame(9))
        buf = await asyncio.wait_for(ws.recv(), 5)
        assert isinstance(buf, bytes)
        header, jpg, height = decode_frame(buf)
        assert header["seq"] == 9 and header["raster_bytes"] == len(jpg) and height is None
        assert jpg[:2] == b"\xff\xd8"
    deadline = time.monotonic() + 5
    while gw.client_count:
        assert time.monotonic() < deadline, "client slot not cleaned up"
        await asyncio.sleep(0.01)
