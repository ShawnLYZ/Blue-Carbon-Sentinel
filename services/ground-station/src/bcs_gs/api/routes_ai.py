"""AI status and call-log routes (addendum I2)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from bcs_gs.ai.export import export_jsonl, query_calls
from bcs_gs.api import models as m

router = APIRouter()


def _filters(
    role: str | None, tier: str | None, status: str | None, from_: str | None, to: str | None, limit: int
) -> dict[str, Any]:
    return {"role": role, "tier": tier, "status": status, "from": from_, "to": to, "limit": limit}


@router.get("/ai/status", response_model=m.AIStatus, summary="Ai status")
async def ai_status(request: Request):
    """Per-role last tier, key health by slot (1-3, never the key), daily counts and Ollama state."""
    return request.app.state.services.ai.status()


@router.get("/ai/calls", response_model=list[m.AICall], summary="Ai calls")
async def ai_calls(
    request: Request,
    role: str | None = Query(None),
    tier: str | None = Query(None),
    status: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Newest first, without inputs and outputs (those are in the export)."""
    repo = request.app.state.services.repo
    rows = await asyncio.to_thread(query_calls, repo, _filters(role, tier, status, from_, to, limit))
    fields = m.AICall.model_fields
    return [m.AICall.model_validate({k: v for k, v in r.items() if k in fields}) for r in rows]


@router.get(
    "/ai/calls/export",
    response_class=StreamingResponse,
    responses={"200": {"content": {"application/x-ndjson": {}}}},
    summary="Ai calls export",
)
async def ai_calls_export(
    request: Request,
    role: str | None = Query(None),
    tier: str | None = Query(None),
    status: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """JSON Lines, oldest first, one attempt per line with inputs and outputs (secrets masked)."""
    repo = request.app.state.services.repo
    lines = await asyncio.to_thread(
        lambda: list(export_jsonl(repo, _filters(role, tier, status, from_, to, limit)))
    )

    def body() -> Iterator[str]:
        for line in lines:
            yield line + "\n"

    return StreamingResponse(body(), media_type="application/x-ndjson")
