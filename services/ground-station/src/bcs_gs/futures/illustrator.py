"""ImageIllustrator (addendum M): NVIDIA FLUX.2 Klein image editing, and the test-mode stand-in.

Request (``NvidiaFluxIllustrator.edit``)::

    POST https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b
    Authorization: Bearer <BCS_NVIDIA_API_KEY>      Accept: application/json
    {"prompt": "<instruction>", "image": ["data:image/jpeg;base64,<1024 x 1024 JPEG>"],
     "width": 1024, "height": 1024, "seed": 42, "steps": 4}

Response (200)::

    {"artifacts": [{"base64": "<image bytes, base64>", "finishReason": "SUCCESS", "seed": 42}]}

A 202 carries an ``NVCF-REQID`` header; the result is then polled from the NVCF status endpoint until it
is ready or the call's timeout (30 s) runs out. A ``finishReason`` other than SUCCESS (e.g.
CONTENT_FILTERED), an empty or undecodable image, or any other body is ``bad_response``.

Errors are ``IllustratorError(kind, detail)``: 401/403 ``auth``; 402/429 ``credits``; 5xx ``server``;
other 4xx ``bad_response``; timeouts ``timeout``; connection failures ``unavailable``. The detail holds the
status code and never the key. The key is used for this endpoint only.

Live check, 2026-10-13 (tests/live/test_live_flux.py once, plus three single diagnostic calls; no key
material recorded):

- The edit request above: **422** in 0.9 s, body ``{"detail": "Expected: example_id, got: base64"}``
  (headers ``nvcf-status: errored``). Authentication passed (422 is validation, after auth).
- Same with the image uploaded as an NVCF asset (``POST https://api.nvcf.nvidia.com/v2/nvcf/assets``, PUT
  to the upload URL, ``"image": ["data:image/jpeg;asset_id,<id>"]`` plus ``NVCF-INPUT-ASSET-REFERENCES``):
  **422** ``{"detail": "Expected: example_id, got: asset_id"}``. The asset was deleted afterwards.
- The same body without ``image`` (text to image): **200** in about 2 s, ``nvcf-status: fulfilled``, body
  ``{"artifacts": [{"base64": "<300004 chars>", "finishReason": "SUCCESS", "seed": 42}]}``, which confirms
  the response format parsed here.

So the hosted API key we have accepts only NVIDIA's example images for editing, never our capture. A
text-to-image result is not an edit of the real site and is not used. Until a deployment that accepts
input images is available, every changed-zone illustration ends ``failed`` with ``bad_response: NVIDIA
returned 422 (Expected: example_id, got: base64)``, and the code-only repaint stands (Review Focus 1).
The request format is kept as the brief specifies so only the image reference changes if that happens.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import time
from typing import Any, Protocol

import cv2
import httpx
import numpy as np

FLUX_MODEL = "black-forest-labs/flux.2-klein-4b"
FLUX_BASE = "https://ai.api.nvidia.com/v1/genai/"
FLUX_URL = FLUX_BASE + FLUX_MODEL
NVCF_STATUS_URL = "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/"
TIMEOUT_S = 30.0
POLL_S = 1.0
KINDS = ("auth", "credits", "server", "timeout", "unavailable", "bad_response")

LIVE_CHECK_RESULT = "422 Expected: example_id, got: base64 (edit of a real image refused); text-only 200"


class IllustratorError(Exception):
    """An illustration could not be made; ``kind`` is one of ``KINDS``."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(kind, detail)
        self.kind, self.detail = kind, detail

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}" if self.detail else self.kind


class ImageIllustrator(Protocol):
    name: str

    async def edit(
        self, image_jpeg: bytes, instruction: str, size: tuple[int, int], seed: int, steps: int
    ) -> bytes: ...


class DisabledIllustrator:
    """Test mode, or no NVIDIA key: every edit is unavailable (the code-only repaint stands)."""

    name = "none"

    def __init__(self, reason: str = "illustrations are disabled") -> None:
        self.reason = reason

    async def edit(
        self, image_jpeg: bytes, instruction: str, size: tuple[int, int], seed: int, steps: int
    ) -> bytes:
        raise IllustratorError("unavailable", self.reason)


def _server_detail(r: httpx.Response) -> str:
    """The short ``detail`` message of an error body, if any (it never carries the key)."""
    try:
        d = r.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    return d[:120] if isinstance(d, str) else ""


def _status_error(code: int, server_detail: str = "") -> IllustratorError:
    detail = f"NVIDIA returned {code}" + (f" ({server_detail})" if server_detail else "")
    if code in (401, 403):
        return IllustratorError("auth", detail)
    if code in (402, 429):
        return IllustratorError("credits", detail)
    if code >= 500:
        return IllustratorError("server", detail)
    return IllustratorError("bad_response", detail)


def _decode_image(payload: Any) -> bytes:
    """The image bytes of a FLUX response body, checked to decode as an image."""
    arts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(arts, list) or not arts or not isinstance(arts[0], dict):
        raise IllustratorError("bad_response", "no artifacts in the response")
    art = arts[0]
    reason = art.get("finishReason", "SUCCESS")
    if reason != "SUCCESS":
        raise IllustratorError("bad_response", f"finishReason {reason}")
    try:
        data = base64.b64decode(art.get("base64") or "", validate=True)
    except (binascii.Error, ValueError):
        raise IllustratorError("bad_response", "the image is not base64") from None
    if not data or cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) is None:
        raise IllustratorError("bad_response", "the image does not decode")
    return data


class NvidiaFluxIllustrator:
    """FLUX.2 Klein image editing on NVIDIA's hosted API (see the module docstring)."""

    name = "nvidia"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = FLUX_MODEL,
        timeout_s: float = TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = api_key
        self.model = model
        self.url = FLUX_BASE + model
        self.timeout_s = timeout_s
        self._transport = transport

    def __repr__(self) -> str:
        return f"NvidiaFluxIllustrator(model={self.model!r})"

    async def edit(
        self, image_jpeg: bytes, instruction: str, size: tuple[int, int], seed: int, steps: int
    ) -> bytes:
        body = {
            "prompt": instruction,
            "image": ["data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode("ascii")],
            "width": int(size[0]), "height": int(size[1]), "seed": int(seed), "steps": int(steps),
        }  # fmt: skip
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        deadline = time.monotonic() + self.timeout_s
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, transport=self._transport) as client:
                r = await client.post(self.url, headers=headers, json=body)
                while r.status_code == 202:
                    req_id = r.headers.get("nvcf-reqid")
                    if not req_id:
                        raise IllustratorError("bad_response", "202 without a request id")
                    if time.monotonic() + POLL_S > deadline:
                        raise IllustratorError("timeout", f"no result within {self.timeout_s:.0f} s")
                    await asyncio.sleep(POLL_S)
                    r = await client.get(NVCF_STATUS_URL + req_id, headers=headers)
        except httpx.TimeoutException:
            raise IllustratorError("timeout", f"no answer within {self.timeout_s:.0f} s") from None
        except httpx.HTTPError as exc:
            raise IllustratorError("unavailable", type(exc).__name__) from None
        if r.status_code != 200:
            raise _status_error(r.status_code, _server_detail(r).replace(self._key, "<redacted>"))
        try:
            payload = r.json()
        except ValueError:
            raise IllustratorError("bad_response", "the response is not JSON") from None
        return _decode_image(payload)
