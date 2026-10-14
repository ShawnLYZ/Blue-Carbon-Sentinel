"""Simulator-facing internal routes (addendum I4). Loopback client and ``X-BCS-Sim-Token`` only."""

from __future__ import annotations

import asyncio
import email
import hmac
import json
import re
from typing import Any

from bcs_protocol.timefmt import to_iso
from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from bcs_gs.api.errors import ApiError

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


async def require_sim(request: Request, x_bcs_sim_token: str | None = Header(None)) -> None:
    host = request.client.host if request.client else ""
    token = request.app.state.services.settings.sim_shared_token
    expected = token.get_secret_value() if token else None
    if (
        host not in LOOPBACK
        or not expected
        or not x_bcs_sim_token
        or not hmac.compare_digest(x_bcs_sim_token, expected)
    ):
        raise ApiError("forbidden", 403, "Internal route: loopback client with a valid simulator token only.")


router = APIRouter(prefix="/internal/sim")
guarded = Depends(require_sim)

_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class CredentialsRequest(BaseModel):
    node_ids: list[str] | None = None


@router.get("/registry", dependencies=[guarded], summary="Simulated node registry")
async def sim_registry(request: Request) -> dict[str, Any]:
    """Active simulated nodes: IDs, types, positions and zone labels. Never keys."""
    svc = request.app.state.services
    nodes = await asyncio.to_thread(svc.nodes.nodes)
    return {
        "site_id": svc.site.site().id,
        "nodes": [
            {
                "node_id": n.id,
                "node_type": n.node_type,
                "position": {"e_m": n.e_m, "s_m": n.s_m},
                "zone_label": n.zone_label,
            }
            for n in nodes
            if n.source == "simulated"
        ],
    }


@router.post("/credentials", dependencies=[guarded], summary="Regenerate simulated node credentials")
async def sim_credentials(request: Request, body: CredentialsRequest | None = None) -> dict[str, Any]:
    """Regenerate the keys of the requested (default: all) simulated nodes, update the broker, return them once."""
    svc = request.app.state.services
    ids = body.node_ids if body else None
    # no key_regenerated event: the caller is the simulator, which already has the keys (an event would
    # make its registry watcher call this again, rotating the key about once a second for ever)
    keys = await asyncio.to_thread(lambda: svc.nodes.provision_simulated(ids, emit=False))
    return {"credentials": [{"node_id": n, "username": n, "password": k} for n, k in keys.items()]}


def _parts(content_type: str, raw: bytes) -> dict[str, bytes]:
    header = b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n"
    msg = email.message_from_bytes(header + raw)
    out: dict[str, bytes] = {}
    if not msg.is_multipart():
        return out
    for part in msg.get_payload():
        name = part.get_param("name", header="content-disposition")
        if isinstance(name, str):
            out[name] = part.get_payload(decode=True) or b""
    return out


def _bad(message: str) -> ApiError:
    return ApiError("validation_error", 422, message)


@router.post("/sessions", dependencies=[guarded], summary="Store a simulator session")
async def sim_sessions(request: Request) -> dict[str, Any]:
    """Multipart ``file`` (K5 JSONL) and ``meta`` (JSON text) -> object in ``sim-sessions`` plus the row."""
    svc = request.app.state.services
    ctype = request.headers.get("content-type", "")
    if not ctype.lower().startswith("multipart/form-data"):
        raise _bad("Expected multipart/form-data with 'file' and 'meta'.")
    parts = _parts(ctype, await request.body())
    if "file" not in parts or "meta" not in parts:
        raise _bad("Both 'file' and 'meta' are required.")
    try:
        meta = json.loads(parts["meta"])
        sid = meta["id"]
        if not isinstance(sid, str) or not _SESSION_ID.match(sid):
            raise ValueError("id")
        row = {
            "id": sid,
            "created_at": str(meta.get("created_at") or to_iso(svc.clock.now())),
            "name": str(meta.get("name") or sid),
            "kind": str(meta.get("kind") or "recording"),
            "seed": None if meta.get("seed") is None else int(meta["seed"]),
            "duration_s": float(meta.get("duration_s", 0.0)),
            "message_count": int(meta.get("message_count", 0)),
            "media_key": f"{sid}.jsonl",
        }
    except (ValueError, KeyError, TypeError):
        raise _bad("'meta' must be a JSON object with a valid 'id' and numeric fields.") from None

    def store() -> None:
        svc.media.put("sim-sessions", row["media_key"], parts["file"], "application/x-ndjson", cloud=True)
        svc.repo.upsert("sim_sessions", row)

    await asyncio.to_thread(store)
    return {"id": sid, "media_key": row["media_key"]}
