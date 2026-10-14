"""Carbon ledger routes (addendum I2). Built in M6: records, checklist, Projected and verify in Task 3;
eligibility in Task 4."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse

from bcs_gs.api import models as m
from bcs_gs.api.errors import ApiError

router = APIRouter()


def _ledger(request: Request):
    return request.app.state.services.ledger


@router.get("/ledger/records", response_model=list[m.LedgerRecord], summary="List records (M6)")
async def list_records(request: Request):
    """Newest first. `link_ok` comes from the latest chain verification (null before one)."""
    return await asyncio.to_thread(_ledger(request).records)


@router.get("/ledger/records/{record_id}", response_model=m.LedgerRecord, summary="Get record (M6)")
async def get_record(request: Request, record_id: str):
    return await asyncio.to_thread(_ledger(request).get, record_id)


@router.get("/ledger/checklist", response_model=m.EvidenceChecklist, summary="Get checklist (M6)")
async def get_checklist(request: Request, plan_id: str | None = Query(None)):
    if not plan_id:
        raise ApiError("validation_error", 422, "The plan_id query parameter is required.")
    return await asyncio.to_thread(_ledger(request).checklist, plan_id)


@router.post("/ledger/projected", response_model=m.LedgerRecord, summary="Append projected (M6)")
async def append_projected(request: Request, body: m.ProjectedRequest | None = None):
    """Appends the Projected record of the plan's applied version, or returns the one it already has.
    422 with `details.checklist` when the evidence checklist is incomplete."""
    if body is None:
        raise ApiError("validation_error", 422, "The plan_id is required.")
    return await _ledger(request).create_projected(body.plan_id)


@router.get("/ledger/eligibility", response_model=list[m.ZoneEligibility], summary="Get eligibility (M6)")
async def get_eligibility(request: Request):
    """Per planted zone of each applied plan with a Projected record: progress against the four Verified
    rules, evaluated now (a zone that passes all four gets its Verified record as a side effect)."""
    return await request.app.state.services.eligibility.evaluate()


@router.post("/ledger/verify", response_model=m.ChainVerification, summary="Verify chain (M6)")
async def verify_chain(request: Request):
    """Re-verifies every record (N13). A broken chain raises `chain_broken` and stops Verified issuance."""
    return await _ledger(request).verify_chain()


@router.get(
    "/ledger/records/{record_id}/evidence-pack",
    response_class=Response,
    responses={"200": {"content": {"application/pdf": {}}}},
    summary="Evidence pack (M6)",
)
async def evidence_pack(request: Request, record_id: str):
    """The record's 8-section PDF, built on the first request and then served from the stored file."""
    path = await request.app.state.services.evidence.get_or_build(record_id)
    return FileResponse(path, media_type="application/pdf", filename=f"{record_id}.pdf")
