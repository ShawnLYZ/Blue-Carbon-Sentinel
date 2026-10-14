"""AI cache keys and input hashing (product spec section 17, addendum A6)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from bcs_gs.ai.providers.base import ProviderRequest


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def cache_key(
    role: str,
    schema_version: str,
    prompt_version: str,
    model: str | None,
    inputs: dict[str, Any],
    image_hashes: list[str],
) -> str:
    """SHA-256 of the canonical JSON (sorted keys, separators ``,`` ``:``) of everything that decides
    an answer."""
    doc = {
        "role": role,
        "schema_version": schema_version,
        "prompt_version": prompt_version,
        "model": model,
        "inputs": inputs,
        "image_hashes": image_hashes,
    }
    return sha256_hex(canonical_json(doc))


def request_inputs(req: ProviderRequest) -> tuple[dict[str, Any], list[str]]:
    """The canonical, loggable inputs of a request (system prompt and text parts) and the SHA-256 of
    each image part. Image bytes are never logged; only their hashes."""
    texts = [p for p in req.parts if isinstance(p, str)]
    images = [sha256_hex(p) for p in req.parts if isinstance(p, bytes | bytearray)]
    return {"system": req.system, "parts": texts}, images
