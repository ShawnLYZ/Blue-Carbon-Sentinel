"""Node routes (addendum I2). Built in M3."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from typing import Any

from bcs_protocol.timefmt import from_iso, to_iso
from fastapi import APIRouter, Query, Request

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.nodes.coverage import ZoneGrid, node_covers
from bcs_gs.tasking.controller import TaskConflict, TaskNotFound

router = APIRouter()

RECENT_TELEMETRY = 50
RECENT_EVENTS = 20
RECENT_TASKS = 10
DEFAULT_SERIES_S = 24 * 3600  # without `from`, a series covers the last day


def to_node(row: Any, grid: ZoneGrid, latest: Any = None) -> m.Node:
    """I3 ``Node`` from a registry row and its newest sample (a TelemetryRow, by ``sampled_at``)."""
    return m.Node(
        id=row.id, node_type=row.node_type, source=row.source,
        position=m.NodePosition(e_m=row.e_m, s_m=row.s_m, lat=row.lat, lng=row.lng, u_px=row.u_px, v_px=row.v_px),
        zone_id=row.zone_id, status=row.status, mode=row.mode, interval_s=row.interval_s,
        fw_version=row.fw_version, last_seen_at=row.last_seen_at,
        covers=m.NodeCovers(**node_covers(row, grid)),
        latest=m.NodeLatest(**latest.latest()) if latest is not None else None,
    )  # fmt: skip


def _svc(request: Request) -> Any:
    return request.app.state.services


def _require_node(svc: Any, node_id: str) -> Any:
    row = svc.nodes.get(node_id)
    if row is None or row.kind != "sentinel_node":
        raise ApiError("not_found", 404, f"No node {node_id}.")
    return row


def _time(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return from_iso(value)
    except ValueError:
        raise ApiError("validation_error", 422, f"{name} must be an ISO 8601 time with a timezone.") from None


@router.get("/nodes", response_model=list[m.Node], summary="List nodes (M3)")
async def list_nodes(request: Request, include_decommissioned: bool = Query(False)):
    svc = _svc(request)

    def load() -> tuple[list[Any], dict[str, Any]]:
        return svc.nodes.nodes(include_decommissioned), svc.ingest.latest_all()

    rows, latest = await asyncio.to_thread(load)
    grid = svc.commissioning.grid
    return [to_node(r, grid, latest.get(r.id)) for r in rows]


@router.get("/nodes/{node_id}", response_model=m.NodeDetail, summary="Get node (M3)")
async def get_node(request: Request, node_id: str):
    svc = _svc(request)

    tasks = await svc.tasking.list_tasks("all", RECENT_TASKS, node_id=node_id)

    def load() -> m.NodeDetail:
        row = _require_node(svc, node_id)
        recent = svc.ingest.recent(node_id, RECENT_TELEMETRY)
        latest = svc.ingest.latest(node_id)
        node = to_node(row, svc.commissioning.grid, latest)
        return m.NodeDetail(
            **node.model_dump(),
            recent_telemetry=[m.TelemetryPoint(**r.point()) for r in recent],
            recent_events=[m.NodeEvent(**e) for e in svc.ingest.events(node_id, RECENT_EVENTS)],
            tasks=tasks,  # newest first
        )

    return await asyncio.to_thread(load)


@router.get("/nodes/{node_id}/telemetry", response_model=m.TelemetrySeries, summary="Node telemetry (M3)")
async def node_telemetry(
    request: Request,
    node_id: str,
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    max_points: int = Query(500, ge=1, le=5000),
):
    svc = _svc(request)
    until = _time(to, "to")
    since = _time(from_, "from") or ((until or svc.clock.now()) - timedelta(seconds=DEFAULT_SERIES_S))

    def load() -> m.TelemetrySeries:
        _require_node(svc, node_id)
        points, downsampled = svc.ingest.series(node_id, since, until, max_points)
        end = until or max([svc.clock.now(), *(from_iso(p["t"]) for p in points[-1:])])
        return m.TelemetrySeries(
            node_id=node_id, from_=to_iso(since), to=to_iso(end), downsampled=downsampled,
            points=[m.TelemetryPoint(**p) for p in points],
        )  # fmt: skip

    return await asyncio.to_thread(load)


@router.get("/nodes/{node_id}/events", response_model=list[m.NodeEvent], summary="Node events (M3)")
async def node_events(request: Request, node_id: str, limit: int = Query(100, ge=1, le=1000)):
    svc = _svc(request)

    def load() -> list[m.NodeEvent]:
        _require_node(svc, node_id)
        return [m.NodeEvent(**e) for e in svc.ingest.events(node_id, limit)]

    return await asyncio.to_thread(load)


async def _publish_coverage(svc: Any) -> None:
    """``coverage.updated`` after a registry change (the same Coverage, gaps included, as GET /coverage)."""
    cov = await asyncio.to_thread(svc.tasking.coverage_now)
    svc.bus.publish("coverage.updated", cov.model_dump(mode="json"))


def _require_active(svc: Any, node_id: str) -> Any:
    row = _require_node(svc, node_id)
    if row.status == "decommissioned":
        raise ApiError("conflict", 409, f"{node_id} is decommissioned.")
    return row


def _confirmed(body: Any) -> None:
    if not (body and body.confirm):
        raise ApiError(
            "confirmation_required", 409, 'This changes an installed node; send {"confirm": true}.'
        )


async def _node(svc: Any, node_id: str) -> m.Node:
    def load() -> m.Node:
        return to_node(_require_node(svc, node_id), svc.commissioning.grid, svc.ingest.latest(node_id))

    return await asyncio.to_thread(load)


@router.post("/nodes", response_model=m.NodeCreated, summary="Create node (M3)")
async def create_node(request: Request, body: m.NodeCreate):
    """Install a node at ``position`` or at a coverage-gap suggestion. A hardware node's key is returned
    once; a simulated node gets ``key: null`` (the simulator re-provisions its credentials, A4)."""
    svc = _svc(request)
    if (body.position is None) == (body.suggestion_id is None):
        raise ApiError("validation_error", 422, "Send exactly one of position or suggestion_id.")
    if body.suggestion_id is not None:
        cov = await asyncio.to_thread(svc.tasking.coverage_now)
        gap = next((g for g in cov.gaps if g.id == body.suggestion_id), None)
        if gap is None:
            raise ApiError("not_found", 404, f"No coverage suggestion {body.suggestion_id}.")
        if gap.node_type != body.node_type:
            raise ApiError("validation_error", 422, f"That suggestion is for a {gap.node_type} node.")
        e_m, s_m = gap.e_m, gap.s_m
    else:
        assert body.position is not None
        e_m, s_m = body.position.e_m, body.position.s_m
    try:
        row, key = await asyncio.to_thread(svc.nodes.install, body.node_type, body.source, e_m, s_m)
    except ValueError as exc:
        raise ApiError("validation_error", 422, str(exc)) from None
    await _publish_coverage(svc)
    node = to_node(row, svc.commissioning.grid, None)
    return m.NodeCreated(node=node, key=key if body.source == "hardware" else None)


@router.post("/nodes/{node_id}/move", response_model=m.Node, summary="Move node (M3)")
async def move_node(request: Request, node_id: str, body: m.NodeMove):
    svc = _svc(request)
    await asyncio.to_thread(_require_active, svc, node_id)
    _confirmed(body)
    try:
        await asyncio.to_thread(svc.nodes.move, node_id, body.position.e_m, body.position.s_m)
    except ValueError as exc:
        raise ApiError("validation_error", 422, str(exc)) from None
    await _publish_coverage(svc)
    return await _node(svc, node_id)


@router.post("/nodes/{node_id}/decommission", response_model=m.Node, summary="Decommission node (M3)")
async def decommission_node(request: Request, node_id: str, body: m.Confirm | None = None):
    svc = _svc(request)
    await asyncio.to_thread(_require_active, svc, node_id)
    _confirmed(body)
    await asyncio.to_thread(svc.nodes.decommission, node_id)
    for task in await svc.tasking.list_tasks("active", 1000, node_id=node_id):  # it can no longer be tasked
        if task.status in ("issued", "active") and node_id in task.node_ids:
            with contextlib.suppress(TaskConflict, TaskNotFound, ValueError):
                await svc.tasking.release(task.id, node_id)
    await _publish_coverage(svc)
    return await _node(svc, node_id)


@router.post("/nodes/{node_id}/regenerate-key", response_model=m.KeyResult, summary="Regenerate key (M3)")
async def regenerate_key(request: Request, node_id: str):
    """Hardware: the new key, once. Simulated: no key; the broker identity is rotated and the simulator
    re-provisions itself (``node.registry`` with ``change="key_regenerated"``)."""
    svc = _svc(request)
    row = await asyncio.to_thread(_require_active, svc, node_id)
    key = await asyncio.to_thread(svc.nodes.regenerate_key, node_id)
    if row.source == "simulated":
        return m.KeyResult(key=None, reprovision="simulator")
    return m.KeyResult(key=key)
