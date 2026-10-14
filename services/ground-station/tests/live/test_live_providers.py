"""Live provider checks: real Gemini keys from ``.env``. Marker ``live``; never in CI, never in a
default run (run by hand: ``uv run pytest services/ground-station/tests/live -m live -q``)."""

from __future__ import annotations

from pathlib import Path

import pytest
from bcs_gs.ai.providers.base import ProviderError, ProviderRequest
from bcs_gs.ai.providers.gemini import GeminiProvider
from bcs_gs.ai.providers.ollama import OllamaProvider
from bcs_gs.core.config import load_settings

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "word": {"type": "string"}},
    "required": ["ok"],
}
SMALL_TEXT_REQ = ProviderRequest(
    "live", "Answer with JSON only.", ['Return {"ok": true, "word": "mangrove"}.'], SCHEMA, 0.2, 30.0
)
MODELS = ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-robotics-er-2-preview"]


def real_keys():
    s = load_settings(ROOT, env_file=ROOT / ".env")
    keys = {i: getattr(s, f"gemini_api_key_{i}") for i in (1, 2, 3)}
    keys = {i: k for i, k in keys.items() if k and k.get_secret_value()}
    if not keys:
        pytest.skip("no Gemini keys in .env")
    return keys


@pytest.mark.live
@pytest.mark.parametrize("model", MODELS)
async def test_live_gemini_model_returns_schema_valid_json(model):
    keys = real_keys()
    try:
        out = await GeminiProvider(keys).generate(model, SMALL_TEXT_REQ, min(keys))
    except ProviderError as e:  # recorded in config/ai.yaml; a failing model is a documented deviation
        pytest.fail(f"{model}: {e.kind}: {e.detail[:200]}")
    assert "ok" in out


@pytest.mark.live
async def test_live_ollama_small_structured_request():
    p = OllamaProvider()
    model = p.pick_model(await p.installed())
    if model is None:
        pytest.skip("no gemma4 installed")
    req = ProviderRequest("live", "Answer with JSON only.", ['Return {"ok": true}.'], SCHEMA, 0.2, 120.0)
    out = await p.generate(model, req, None)
    assert "ok" in out
