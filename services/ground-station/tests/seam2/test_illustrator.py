"""NvidiaFluxIllustrator request, response parsing and error kinds (M5 Task 6), over httpx.MockTransport.
Never reaches NVIDIA."""

from __future__ import annotations

import base64
import json

import cv2
import httpx
import numpy as np
import pytest
from bcs_gs.futures.illustrator import (
    FLUX_URL,
    DisabledIllustrator,
    IllustratorError,
    NvidiaFluxIllustrator,
)

KEY = "nvapi-test-key-value"


def _jpeg(seed: int = 1, size: int = 64) -> bytes:
    img = np.random.default_rng(seed).integers(0, 256, (size, size, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def _flux(handler) -> NvidiaFluxIllustrator:
    return NvidiaFluxIllustrator(KEY, transport=httpx.MockTransport(handler))


async def test_request_body_and_artifacts_response():
    seen = {}
    out_bytes = _jpeg(2)

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        b64 = base64.b64encode(out_bytes).decode()
        return httpx.Response(
            200, json={"artifacts": [{"base64": b64, "finishReason": "SUCCESS", "seed": 42}]}
        )

    got = await _flux(handler).edit(_jpeg(1), "Make it so.", (1024, 1024), 42, 4)
    assert got == out_bytes
    assert seen["url"] == FLUX_URL == "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b"
    assert seen["auth"] == f"Bearer {KEY}"
    body = seen["body"]
    assert body["prompt"] == "Make it so." and body["width"] == 1024 and body["height"] == 1024
    assert body["seed"] == 42 and body["steps"] == 4
    assert isinstance(body["image"], list) and body["image"][0].startswith("data:image/jpeg;base64,")
    assert base64.b64decode(body["image"][0].split(",", 1)[1]) == _jpeg(1)


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, "auth"), (403, "auth"), (402, "credits"), (429, "credits"), (500, "server"), (503, "server"),
     (400, "bad_response"), (422, "bad_response")],
)  # fmt: skip
async def test_http_status_maps_to_error_kind(status, kind):
    flux = _flux(lambda req: httpx.Response(status, json={"detail": "nope"}))
    with pytest.raises(IllustratorError) as ei:
        await flux.edit(_jpeg(), "x", (1024, 1024), 42, 4)
    assert ei.value.kind == kind and str(status) in ei.value.detail
    assert KEY not in str(ei.value)


async def test_timeout_and_connection_errors_map_to_kinds():
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)

    def down(req):
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(IllustratorError) as ei:
        await _flux(slow).edit(_jpeg(), "x", (1024, 1024), 42, 4)
    assert ei.value.kind == "timeout"
    with pytest.raises(IllustratorError) as ei:
        await _flux(down).edit(_jpeg(), "x", (1024, 1024), 42, 4)
    assert ei.value.kind == "unavailable"


@pytest.mark.parametrize(
    "payload",
    [{"artifacts": []}, {"artifacts": [{"base64": "!!!notbase64", "finishReason": "SUCCESS"}]},
     {"artifacts": [{"base64": base64.b64encode(b"not an image").decode(), "finishReason": "SUCCESS"}]},
     {"artifacts": [{"base64": "", "finishReason": "CONTENT_FILTERED"}]}, {"something": "else"}],
)  # fmt: skip
async def test_unusable_response_is_bad_response(payload):
    with pytest.raises(IllustratorError) as ei:
        await _flux(lambda req: httpx.Response(200, json=payload)).edit(_jpeg(), "x", (1024, 1024), 42, 4)
    assert ei.value.kind == "bad_response"


async def test_non_json_200_is_bad_response():
    flux = _flux(lambda req: httpx.Response(200, content=b"<html>"))
    with pytest.raises(IllustratorError) as ei:
        await flux.edit(_jpeg(), "x", (1024, 1024), 42, 4)
    assert ei.value.kind == "bad_response"


async def test_disabled_illustrator_is_always_unavailable():
    with pytest.raises(IllustratorError) as ei:
        await DisabledIllustrator().edit(_jpeg(), "x", (1024, 1024), 42, 4)
    assert ei.value.kind == "unavailable"


def test_error_str_never_contains_the_key_and_repr_hides_it():
    flux = NvidiaFluxIllustrator(KEY)
    assert KEY not in repr(flux)
    assert str(IllustratorError("auth", "NVIDIA returned 401")) == "auth: NVIDIA returned 401"
