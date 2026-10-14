"""Evidence pack charts: matplotlib on the Agg backend, rendered to PNG in memory (never pyplot, so the
builder can run on any worker thread)."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from typing import Any

import matplotlib

matplotlib.use("Agg")

from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure

MYT = timezone(timedelta(hours=8))
GREEN, GREY, RED, BLUE = "#1b7f4a", "#6b7280", "#b42318", "#1d4ed8"
MAX_PANELS = 6
DPI = 150


def _png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight")
    return buf.getvalue()


def sensor_chart_png(node_id: str, samples: list[tuple[datetime, dict[str, float]]]) -> bytes:
    """One panel per reading (up to six) of a covering node over the window; times shown in MYT."""
    keys = sorted({k for _, r in samples for k in r})[:MAX_PANELS]
    fig = Figure(figsize=(7.0, max(1.6, 1.25 * max(len(keys), 1) + 0.5)))
    if not keys:
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, "no samples in this window", ha="center", va="center", color=GREY)
        ax.set_axis_off()
    else:
        axes = fig.subplots(len(keys), 1, sharex=True, squeeze=False)[:, 0]
        for ax, key in zip(axes, keys, strict=True):
            pts = [(t.astimezone(MYT), r[key]) for t, r in samples if key in r]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=BLUE, linewidth=1.2)
            ax.set_ylabel(key, fontsize=7)
            ax.tick_params(labelsize=7)
            ax.grid(alpha=0.25)
        axes[-1].xaxis.set_major_formatter(DateFormatter("%H:%M:%S", tz=MYT))
        axes[-1].set_xlabel("time (MYT)", fontsize=7)
    fig.suptitle(f"{node_id} (SIMULATED)", fontsize=9, color=RED)
    fig.tight_layout()
    return _png(fig)


def forecast_chart_png(
    zone_id: str,
    years: list[int],
    without: list[tuple[float, float, float]],
    with_: list[tuple[float, float, float]],
    ylabel: str,
    title: str,
) -> bytes:
    """Low / central / high bands of the without and with-plan scenarios for one zone."""
    fig = Figure(figsize=(7.0, 2.6))
    ax = fig.add_subplot(111)
    for name, series, colour in (("without plan", without, GREY), ("with plan", with_, GREEN)):
        ax.fill_between(years, [s[0] for s in series], [s[2] for s in series], color=colour, alpha=0.18)
        ax.plot(years, [s[1] for s in series], color=colour, linewidth=1.6, label=f"{name} (central)")
    ax.set_ylabel(ylabel, fontsize=8)
    ax.set_title(f"{zone_id}: {title}", fontsize=9)
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    return _png(fig)


def ndvi_proxy_png(vari: Any) -> bytes:
    """The VARI map (NDVI proxy, -1..1) colour-mapped."""
    fig = Figure(figsize=(4.0, 3.0))
    ax = fig.add_subplot(111)
    im = ax.imshow(vari, cmap="RdYlGn", vmin=-1.0, vmax=1.0)
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02).ax.tick_params(labelsize=6)
    fig.tight_layout()
    return _png(fig)
