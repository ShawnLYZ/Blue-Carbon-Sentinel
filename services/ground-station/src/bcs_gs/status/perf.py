"""Performance probe against the design section 33 targets (``bcs-gs perf``).

``perf_report`` is pure: it judges samples against the targets. The collectors below read a running
Ground Station (live socket, status endpoint) and its store (read-only) and never write to either.

Aggregation per metric (a single bad frame must not fail a ">=" rate, and one slow outlier must be
visible in a "<=" latency):
  * ">=" targets (live_fps, render_fps) are judged on the median sample;
  * "<=" latency targets are judged on the 95th percentile (nearest rank);
  * "typical AI" (ai_s) is judged on the median, as the target says typical;
  * a metric with no samples gets no row; it is listed in ``no_samples`` and never counts as failed.

What each source really measures (honest limits):
  * frame_to_screen_ms is the server part only (``latency_ms`` of the live frame header). The browser part
    is shown on System -> Live surface; it cannot be seen from here.
  * telemetry_to_ui_s is ``received_at - sampled_at`` of stored telemetry (the Ground Station part).
  * ai_s is model calls only (cache hits and the rules tier are excluded).
  * forecast_fresh_s is the stored forecasts' ``summary.elapsed_ms`` (last hour).
  * capture_s, change_capture_s, forecast_cached_s, flux_s and render_fps have no recorded source yet; they
    are accepted (tests, future instrumentation) and reported as "no samples" by the CLI today.
"""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from bcs_protocol.timefmt import from_iso, to_iso

DB_LOOKBACK = timedelta(hours=1)  # stored telemetry, commands and AI calls newer than this are sampled


@dataclass
class PerfSamples:
    live_fps: list[float] = field(default_factory=list)
    latency_ms: list[float] = field(default_factory=list)
    capture_s: list[float] = field(default_factory=list)
    telemetry_to_ui_s: list[float] = field(default_factory=list)
    ack_s: list[float] = field(default_factory=list)
    ai_s: list[float] = field(default_factory=list)
    sync_lag_s: list[float] = field(default_factory=list)
    start_to_ready_s: list[float] = field(default_factory=list)
    change_capture_s: list[float] = field(default_factory=list)
    forecast_cached_s: list[float] = field(default_factory=list)
    forecast_fresh_s: list[float] = field(default_factory=list)
    flux_s: list[float] = field(default_factory=list)
    render_fps: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class _Spec:
    metric: str
    field: str
    label: str
    op: Literal[">=", "<="]
    target: float
    unit: str
    agg: Literal["median", "p95"]


# Order is the table order. Targets are design section 33.
SPECS: tuple[_Spec, ...] = (
    _Spec("live_fps", "live_fps", "Live surface", ">=", 5, "fps", "median"),
    _Spec("frame_to_screen_ms", "latency_ms", "Frame to screen (server part)", "<=", 500, "ms", "p95"),
    _Spec("capture_s", "capture_s", "Capture analysis", "<=", 1.5, "s", "p95"),
    _Spec("change_capture_s", "change_capture_s", "Change capture after stable", "<=", 5, "s", "p95"),
    _Spec("telemetry_to_ui_s", "telemetry_to_ui_s", "Telemetry to UI (receipt delay)", "<=", 1, "s", "p95"),
    _Spec("ack_s", "ack_s", "Command to ack", "<=", 2, "s", "p95"),
    _Spec("ai_s", "ai_s", "Typical AI", "<=", 10, "s", "median"),
    _Spec("forecast_cached_s", "forecast_cached_s", "Forecast (cached)", "<=", 1, "s", "p95"),
    _Spec("forecast_fresh_s", "forecast_fresh_s", "Forecast (fresh)", "<=", 20, "s", "p95"),
    _Spec("flux_s", "flux_s", "FLUX", "<=", 60, "s", "p95"),
    _Spec("render_fps", "render_fps", "Rendering", ">=", 30, "fps", "median"),
    _Spec("sync_lag_s", "sync_lag_s", "Sync lag online", "<=", 2, "s", "p95"),
    _Spec("start_to_ready_s", "start_to_ready_s", "Start to ready", "<=", 60, "s", "p95"),
)


@dataclass
class PerfRow:
    metric: str
    label: str
    value: float
    target: float
    op: str
    unit: str
    aggregation: str
    samples: int
    ok: bool


@dataclass
class PerfReport:
    rows: list[PerfRow]
    no_samples: list[str]

    @property
    def ok(self) -> bool:
        """True when every measured row passes (metrics without samples do not fail)."""
        return all(r.ok for r in self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "rows": [asdict(r) for r in self.rows], "no_samples": self.no_samples}


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def perf_report(samples: PerfSamples) -> PerfReport:
    rows: list[PerfRow] = []
    missing: list[str] = []
    for spec in SPECS:
        values: list[float] = list(getattr(samples, spec.field))
        if not values:
            missing.append(spec.metric)
            continue
        value = statistics.median(values) if spec.agg == "median" else _p95(values)
        ok = value >= spec.target if spec.op == ">=" else value <= spec.target
        rows.append(
            PerfRow(spec.metric, spec.label, round(value, 3), spec.target, spec.op, spec.unit, spec.agg, len(values), ok)
        )
    return PerfReport(rows, missing)


def format_table(report: PerfReport) -> str:
    lines = [f"{'metric':<22}{'value':>10}  {'target':<12}{'n':>5}  {'agg':<7}result"]
    for r in report.rows:
        target = f"{r.op} {r.target:g} {r.unit}"
        lines.append(
            f"{r.metric:<22}{r.value:>10g}  {target:<12}{r.samples:>5}  {r.aggregation:<7}" + ("ok" if r.ok else "FAIL")
        )
    for name in report.no_samples:
        lines.append(f"{name:<22}{'no samples':>10}")
    return "\n".join(lines)


# ---- collectors ----------------------------------------------------------------------------------


def _note(msg: str) -> None:
    print(f"perf: {msg}", file=sys.stderr)


async def collect_live(ws_url: str, seconds: float, samples: PerfSamples) -> None:
    """Read live frames for ``seconds``: frames per whole second received, header ``latency_ms`` per frame."""
    import websockets

    from bcs_gs.live.codec import MAGIC

    per_second: dict[int, int] = {}
    t0 = time.monotonic()
    try:
        async with websockets.connect(ws_url, max_size=None) as ws:
            while (left := seconds - (time.monotonic() - t0)) > 0:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=min(left, 1.0))
                except TimeoutError:
                    continue
                if not isinstance(msg, bytes) or msg[:4] != MAGIC:
                    continue
                hlen = int.from_bytes(msg[8:12], "little")
                header = json.loads(msg[12 : 12 + hlen])
                sec = int(time.monotonic() - t0)
                per_second[sec] = per_second.get(sec, 0) + 1
                samples.latency_ms.append(float(header["latency_ms"]))
    except (OSError, websockets.WebSocketException) as exc:
        _note(f"live surface not read ({type(exc).__name__}: {exc})")
        return  # not reachable: the metrics simply have no samples
    # The final second can be partial, so only whole elapsed seconds count.
    whole = int(seconds)
    samples.live_fps.extend(float(per_second.get(s, 0)) for s in range(whole) if per_second)


def sync_lag_sample(status: dict[str, Any]) -> float | None:
    """The sync lag of one ``/system/status`` read while sync is healthy (no failed pass since the last good
    one), else None. ``lag_s`` is the age of the oldest queued row, set only while rows wait ("buffering"
    without failures is healthy); an empty queue is zero lag."""
    sync = status["sync"]
    comp = next((c for c in status.get("components", []) if c.get("id") == "sync"), None)
    failures = int(((comp or {}).get("details") or {}).get("failures", 0))
    if sync["state"] == "offline" or failures > 0:
        return None
    return float(sync["lag_s"]) if sync["lag_s"] is not None else 0.0


async def collect_sync_lag(http_url: str, seconds: float, samples: PerfSamples) -> None:
    import httpx

    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=3) as client:
        while time.monotonic() - t0 < seconds:
            try:
                lag = sync_lag_sample((await client.get(f"{http_url}/api/v1/system/status")).json())
                if lag is not None:
                    samples.sync_lag_s.append(lag)
            except (ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
                _note(f"sync lag not read ({type(exc).__name__}: {exc})")
            await asyncio.sleep(max(0.0, min(2.0, seconds - (time.monotonic() - t0))))


def _rows(con: sqlite3.Connection, name: str, sql: str, params: tuple[str, ...]) -> list[tuple[Any, ...]]:
    try:
        return con.execute(sql, params).fetchall()
    except sqlite3.Error as exc:  # an older or locked store: this metric has no samples
        _note(f"{name} not read ({exc})")
        return []


def collect_store(db_path: Path, now: datetime, samples: PerfSamples) -> None:
    """Receipt delay, command-to-ack, AI latency and forecast time from the last hour of the store (read-only)."""
    if not db_path.is_file():
        return
    since = (to_iso(now - DB_LOOKBACK),)
    try:
        con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        _note(f"store not opened ({exc})")
        return
    try:
        for sampled, received in _rows(
            con, "telemetry",
            "SELECT sampled_at, received_at FROM telemetry WHERE received_at >= ? AND replay = 0 AND late = 0", since,
        ):  # fmt: skip
            samples.telemetry_to_ui_s.append((from_iso(received) - from_iso(sampled)).total_seconds())
        for issued, acked in _rows(
            con, "commands",
            "SELECT issued_at, ack_at FROM commands WHERE issued_at >= ? AND ack_at IS NOT NULL AND ack_status = 'accepted'",
            since,
        ):  # fmt: skip
            samples.ack_s.append((from_iso(acked) - from_iso(issued)).total_seconds())
        for (ms,) in _rows(
            con, "ai_calls",
            "SELECT latency_ms FROM ai_calls WHERE at >= ? AND latency_ms IS NOT NULL AND cache_hit = 0 "
            "AND status = 'success' AND tier != 'rules'",
            since,
        ):  # fmt: skip
            samples.ai_s.append(ms / 1000)
        # Stored forecasts are fresh computations; their own elapsed time is the fresh-forecast sample.
        for (elapsed_ms,) in _rows(
            con, "forecasts",
            "SELECT json_extract(summary, '$.elapsed_ms') FROM forecasts WHERE created_at >= ? AND status = 'ready' "
            "AND json_extract(summary, '$.elapsed_ms') IS NOT NULL",
            since,
        ):  # fmt: skip
            samples.forecast_fresh_s.append(float(elapsed_ms) / 1000)
    finally:
        con.close()


async def run_probe(
    host: str, port: int, seconds: float, data_dir: Path, start_to_ready_s: float | None = None
) -> PerfReport:
    samples = PerfSamples()
    if start_to_ready_s is not None:
        samples.start_to_ready_s.append(start_to_ready_s)
    await asyncio.gather(
        collect_live(f"ws://{host}:{port}/ws/live", seconds, samples),
        collect_sync_lag(f"http://{host}:{port}", seconds, samples),
    )
    collect_store(data_dir / "var" / "bcs.sqlite3", datetime.now(UTC), samples)
    return perf_report(samples)
