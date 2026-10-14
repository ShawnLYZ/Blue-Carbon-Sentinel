"""The Demo Director steps (design §27, addendum F5): captions, actions and the real event that advances each.

``advance_on(event, ctx)`` is called only for the *current* step. It may record progress in ``ctx`` (a
telemetry counter, the half-done restore) and returns True when the step's real trigger has happened. The
Director never fabricates an event: nothing here advances a step except an event from the bus.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bcs_gs.core.events import Event

MEASURE_SAMPLES = 5  # investigation-mode telemetry samples that count as "measured"

FLAG_LABELS = {
    "canopy_loss": ("canopy loss", "pp"),
    "dieback": ("dieback", "%"),
    "index_drop": ("VARI drop", ""),
    "discolouration": ("discolouration", "%"),
    "new_growth": ("new growth", "pp"),
}


@dataclass
class Context:
    """What earlier steps found; later steps use it to recognise their own events."""

    flagged_zone_id: str | None = None
    task_id: str | None = None
    tasked_node_ids: list[str] = field(default_factory=list)
    forecast_id: str | None = None
    plan_id: str | None = None
    planted_zone_ids: list[str] = field(default_factory=list)
    # Progress inside the current step (cleared by retry/skip of that step).
    step_started_at: datetime | None = None
    measure_samples: int = 0
    plan_applied: bool = False

    def clear_progress(self, key: str) -> None:
        """Forget the partial progress of step ``key`` only; what other steps found stays."""
        if key == "measure":
            self.measure_samples = 0
        elif key == "restore":
            self.plan_applied = False
            self.plan_id = None
            self.planted_zone_ids = []

    def note_plan(self, data: dict[str, Any]) -> None:
        """A plan was applied (seen at any time during a run, e.g. while predict was current)."""
        self.plan_applied = True
        self.plan_id = data.get("plan_id")
        self.planted_zone_ids = list(data.get("zones") or [])


@dataclass(frozen=True)
class StepDef:
    key: str
    n: int
    caption: str
    action: str | None
    needs_camera: bool
    advance_on: Callable[[Event, Context], bool]
    summarize: Callable[[Event, Context], str]


def _label(zone_id: str | None) -> str:
    return (zone_id or "?").split("-")[-1]


def _flags_text(flags: list[dict[str, Any]]) -> str:
    parts = []
    for f in flags:
        name, unit = FLAG_LABELS.get(f.get("kind"), (str(f.get("kind")), ""))
        parts.append(f"{name} {float(f.get('value', 0)):.1f}{(' ' + unit) if unit else ''}")
    return ", ".join(parts) or "change"


# ---- early_warning -------------------------------------------------------------------------------
def _early_warning_on(ev: Event, ctx: Context) -> bool:
    return ev.type == "zone.assessed" and bool(ev.data.get("early_warning"))


def _early_warning_sum(ev: Event, ctx: Context) -> str:
    return f"Early warning for zone {_label(ev.data.get('zone_id'))}: risk {ev.data.get('risk_class')}"


# ---- detect --------------------------------------------------------------------------------------
def _detect_on(ev: Event, ctx: Context) -> bool:
    if ev.type != "zone.flagged":
        return False
    ctx.flagged_zone_id = ev.data.get("zone_id")
    return True


def _detect_sum(ev: Event, ctx: Context) -> str:
    return f"Zone {_label(ev.data.get('zone_id'))} flagged: {_flags_text(ev.data.get('flags') or [])}"


# ---- task ----------------------------------------------------------------------------------------
def _task_on(ev: Event, ctx: Context) -> bool:
    if ev.type != "task.updated":
        return False
    # No created_at comparison: the automatic task is created by tasking from the same zone.flagged that
    # completes detect (before this step began), and an extended task keeps its old created_at. What counts
    # is an accepted command ack observed while this step is current.
    d = ev.data
    if not any(c.get("ack_status") == "accepted" for c in d.get("commands") or []):
        return False
    ctx.task_id = d["id"]
    ctx.tasked_node_ids = list(d.get("node_ids") or [])
    return True


def _task_sum(ev: Event, ctx: Context) -> str:
    n = len(ev.data.get("node_ids") or [])
    return f"Task for zone {_label(ev.data.get('zone_id'))} accepted by {n} node{'s' if n != 1 else ''}"


# ---- measure -------------------------------------------------------------------------------------
def _measure_on(ev: Event, ctx: Context) -> bool:
    # If the task step was skipped, tasked_node_ids is empty: samples from any node in investigation mode count.
    if ev.type != "node.telemetry" or ev.data.get("mode") != "investigation":
        return False
    if ctx.tasked_node_ids and ev.data.get("node_id") not in ctx.tasked_node_ids:
        return False
    ctx.measure_samples += 1
    return ctx.measure_samples >= MEASURE_SAMPLES


def _measure_sum(ev: Event, ctx: Context) -> str:
    return f"{ctx.measure_samples} investigation-mode samples received"


# ---- fuse ----------------------------------------------------------------------------------------
def _fuse_on(ev: Event, ctx: Context) -> bool:
    # If the detect step was skipped the flagged zone is unknown: any assessment with a narrative counts.
    # Otherwise only the flagged zone counts.
    if ev.type != "zone.assessed" or not (ev.data.get("narrative") or "").strip():
        return False
    return ctx.flagged_zone_id is None or ev.data.get("zone_id") == ctx.flagged_zone_id


def _fuse_sum(ev: Event, ctx: Context) -> str:
    return f"Zone {_label(ev.data.get('zone_id'))} assessed: {ev.data.get('risk_class')} risk"


# ---- predict -------------------------------------------------------------------------------------
def _predict_on(ev: Event, ctx: Context) -> bool:
    if ev.type != "forecast.ready" or ev.data.get("status") != "ready":
        return False
    ctx.forecast_id = ev.data.get("forecast_id")
    return True


def _predict_sum(ev: Event, ctx: Context) -> str:
    return "Forecast ready: scrub Time Travel to 2035"


# ---- restore (two phases: plan applied, then new growth in a planted zone) -----------------------
def _restore_on(ev: Event, ctx: Context) -> bool:
    d = ev.data
    if ev.type == "plan.updated" and d.get("status") == "applied":
        ctx.note_plan(d)
        return False
    if ev.type == "zone.flagged" and ctx.plan_applied and d.get("zone_id") in ctx.planted_zone_ids:
        return any(f.get("kind") == "new_growth" for f in d.get("flags") or [])
    return False


def _restore_sum(ev: Event, ctx: Context) -> str:
    return f"Zone {_label(ev.data.get('zone_id'))} flagged: {_flags_text(ev.data.get('flags') or [])}"


# ---- verify --------------------------------------------------------------------------------------
def _verify_on(ev: Event, ctx: Context) -> bool:
    return ev.type == "ledger.appended" and ev.data.get("type") == "verified"


def _verify_sum(ev: Event, ctx: Context) -> str:
    return f"Verified record #{ev.data.get('chain_index')}: {ev.data.get('quantity_tco2e')} tCO2e"


EARLY_WARNING = StepDef(
    "early_warning", 0, "Optional: sensors warn before the camera can see it", "Apply a sensor scenario first",
    False, _early_warning_on, _early_warning_sum,
)  # fmt: skip

STEPS: list[StepDef] = [
    StepDef("detect", 1, "Detect: the camera flags a change", "Brown or remove a tree", True, _detect_on, _detect_sum),
    StepDef("task", 2, "Task: sensors are tasked to investigate", None, False, _task_on, _task_sum),
    StepDef(
        "measure", 3, "Measure: sensors sample the zone", "Apply a scenario to the zone in the Simulator Console",
        False, _measure_on, _measure_sum,
    ),
    StepDef("fuse", 4, "Fuse: evidence becomes a risk assessment", None, False, _fuse_on, _fuse_sum),
    StepDef("predict", 5, "Predict: the 2026-2035 forecast", "Opens Time Travel", False, _predict_on, _predict_sum),
    StepDef(
        "restore", 6, "Restore: plan and plant", "Propose/edit/apply plan, then plant clay saplings",
        True, _restore_on, _restore_sum,
    ),
    StepDef(
        "verify", 7, "Verify: carbon is recorded on the ledger", "Generate Projected record", False,
        _verify_on, _verify_sum,
    ),
]  # fmt: skip
