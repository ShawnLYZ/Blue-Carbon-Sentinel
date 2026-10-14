"""Event payload models of ``/ws/events`` (addendum J2); source for ``export-event-schemas``."""

from __future__ import annotations

from functools import reduce
from operator import or_
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, create_model

from bcs_gs.api import models as m


class Hello(BaseModel):
    server_time: str
    version: str
    demo_time_scale: bool


class CaptureRef(BaseModel):
    capture_id: str


class ZoneMetricsEvent(BaseModel):
    capture_id: str
    metrics: list[m.ZoneMetrics]


class ZoneFlaggedEvent(BaseModel):
    capture_id: str
    zone_id: str
    flags: list[m.ZoneFlag]


class NodeTelemetryEvent(BaseModel):
    node_id: str
    sampled_at: str
    mode: str
    readings: dict[str, float]
    health: m.Health
    flags: list[m.EdgeFlag]
    late: bool
    source: Literal["simulated", "hardware"]
    replay: bool


class NodeStatusEvent(BaseModel):
    node_id: str
    state: str
    mode: str | None
    interval_s: float | None
    at: str
    reason: str | None


class NodeRegistryEvent(BaseModel):
    change: str
    node_ids: list[str]
    commissioning_run_id: str | None = None


class AlertAcknowledged(BaseModel):
    id: str
    acknowledged_at: str


class GenerationRef(BaseModel):
    generation_id: str


class ForecastReady(BaseModel):
    forecast_id: str
    plan_id: str | None
    status: str


class LedgerAppended(BaseModel):
    chain_index: int
    record_id: str
    type: str
    quantity_tco2e: str


# J2 event type -> data model
EVENT_DATA: dict[str, type[BaseModel]] = {
    "hello": Hello,
    "system.status": m.SystemStatus,
    "sync.status": m.SyncState,
    "camera.status": m.CameraStatus,
    "calibration.updated": m.Calibration,
    "baseline.updated": CaptureRef,
    "capture.created": m.CaptureSummary,
    "zone.metrics": ZoneMetricsEvent,
    "zone.flagged": ZoneFlaggedEvent,
    "node.telemetry": NodeTelemetryEvent,
    "node.status": NodeStatusEvent,
    "node.event": m.NodeEvent,
    "node.registry": NodeRegistryEvent,
    "task.updated": m.Task,
    "coverage.updated": m.Coverage,
    "zone.assessed": m.Assessment,
    "trees.updated": m.TreePoints,
    "ai.call": m.AICall,
    "alert.created": m.Alert,
    "alert.acknowledged": AlertAcknowledged,
    "history.updated": GenerationRef,
    "plan.updated": m.PlanSummary,
    "forecast.ready": ForecastReady,
    "illustration.ready": m.Illustration,
    "ledger.appended": LedgerAppended,
    "ledger.verified": m.ChainVerification,
    "director.state": m.DirectorState,
}


def event_schema() -> dict[str, Any]:
    """JSON Schema of the envelope as a union discriminated by ``type``."""
    variants = [
        create_model(
            "Event_" + name.replace(".", "_"),
            v=(Literal[1], 1),
            type=(Literal[name], name),
            id=(str, ...),
            at=(str, ...),
            data=(model, ...),
        )
        for name, model in EVENT_DATA.items()
    ]
    union = Annotated[reduce(or_, variants), Field(discriminator="type")]
    schema = TypeAdapter(union).json_schema(ref_template="#/$defs/{model}")
    schema["title"] = "EventEnvelope"
    return schema
