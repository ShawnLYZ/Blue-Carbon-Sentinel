"""Investigation task routes (addendum I2). Built in M3."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError
from bcs_gs.tasking.controller import NoCoverage, TaskConflict, TaskNotFound

router = APIRouter()


def _tasking(request: Request):
    return request.app.state.services.tasking


@router.get("/tasks", response_model=list[m.Task], summary="List tasks (M3)")
async def list_tasks(
    request: Request,
    status: str = Query("active", pattern="^(active|all)$"),
    limit: int = Query(100, ge=1, le=1000),
):
    """``active``: open tasks plus those updated in the last 10 minutes; ``all``: every task. Newest first."""
    return await _tasking(request).list_tasks(status, limit)


@router.post("/tasks", response_model=m.Task, summary="Create task (M3)")
async def create_task(request: Request, body: m.TaskCreate | None = None):
    """A manual task for a zone (its covering nodes) and/or explicit nodes. An open task for the zone is
    extended instead. The per-zone cooldown does not apply to the operator."""
    body = body or m.TaskCreate()
    if not body.zone_id and not body.node_ids:
        raise ApiError("validation_error", 422, "A task needs a zone_id or node_ids.")
    if body.duration_s is not None and body.duration_s <= 0:
        raise ApiError("validation_error", 422, "duration_s must be greater than 0.")
    reason = (
        body.reason or ""
    ).strip() or f"manual task for {body.zone_id or ', '.join(body.node_ids or [])}"
    try:
        task = await _tasking(request).trigger(
            body.zone_id, "manual", reason[:200], node_ids=body.node_ids, duration_s=body.duration_s
        )
    except ValueError as exc:
        raise ApiError("validation_error", 422, str(exc)) from None
    except NoCoverage as exc:
        raise ApiError("conflict", 409, str(exc), {"zone_id": body.zone_id}) from None
    assert task is not None  # manual triggers never fall in a cooldown
    return task


@router.post("/tasks/{task_id}/cancel", response_model=m.Task, summary="Cancel task (M3)")
async def cancel_task(request: Request, task_id: str):
    try:
        return await _tasking(request).cancel(task_id, by="operator")
    except TaskNotFound:
        raise ApiError("not_found", 404, f"No task {task_id}.") from None
    except TaskConflict as exc:
        raise ApiError("conflict", 409, str(exc)) from None


@router.post("/tasks/{task_id}/release", response_model=m.Task, summary="Release task (M3)")
async def release_task(request: Request, task_id: str, body: m.TaskRelease):
    try:
        return await _tasking(request).release(task_id, body.node_id)
    except TaskNotFound:
        raise ApiError("not_found", 404, f"No task {task_id}.") from None
    except TaskConflict as exc:
        raise ApiError("conflict", 409, str(exc)) from None
    except ValueError as exc:
        raise ApiError("validation_error", 422, str(exc)) from None
