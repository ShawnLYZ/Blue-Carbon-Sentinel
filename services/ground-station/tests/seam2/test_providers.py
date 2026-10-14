"""Seam-2 tests of the Gemini, Ollama and Rules providers (no network: a fake genai client and
``httpx.MockTransport``)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from bcs_gs.ai.providers.base import ProviderError, ProviderRequest
from bcs_gs.ai.providers.gemini import GeminiProvider
from bcs_gs.ai.providers.ollama import OllamaProvider
from bcs_gs.ai.providers.rules import RulesProvider
from google.genai import errors
from pydantic import BaseModel, SecretStr

KEYS = {1: SecretStr("key-one-secret"), 2: SecretStr("key-two-secret"), 3: SecretStr("key-three-secret")}
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
REQ = ProviderRequest("t", "sys", ["hello"], SCHEMA, 0.2, 5.0)
REQ_WITH_IMAGE = ProviderRequest("t", "sys", ["look", b"\xff\xd8jpeg"], SCHEMA, 0.2, 5.0)


class FakeGenai:
    """Stands in for ``google.genai.Client``: records what was sent, plays scripted outcomes."""

    def __init__(self) -> None:
        self.next_error: BaseException | None = None
        self.next_text: str = '{"ok": true}'
        self.last_config: Any = None
        self.last_parts: list[Any] = []
        self.last_model: str | None = None
        self.last_key_slot: int | None = None

    def factory(self, api_key: str) -> Any:
        slot = next(s for s, k in KEYS.items() if k.get_secret_value() == api_key)

        async def generate_content(*, model: str, contents: list[Any], config: Any) -> Any:
            self.last_key_slot, self.last_model = slot, model
            self.last_config, self.last_parts = config, contents
            if self.next_error is not None:
                raise self.next_error
            if self.next_text == "hang":
                await asyncio.sleep(30)
            return SimpleNamespace(text=self.next_text)

        return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))


@pytest.fixture
def fake_genai() -> FakeGenai:
    return FakeGenai()


def api_error(status: int) -> errors.APIError:
    return errors.APIError(status, {"error": {"code": status, "message": "boom key-one-secret"}})


def gem(fake: FakeGenai, **kw: Any) -> GeminiProvider:
    return GeminiProvider(KEYS, client_factory=fake.factory, **kw)


async def test_gemini_maps_http_errors_to_kinds(fake_genai):
    for status, kind in [(429, "rate_limited"), (503, "overloaded"), (500, "overloaded"), (504, "timeout")]:
        fake_genai.next_error = api_error(status)
        with pytest.raises(ProviderError) as e:
            await gem(fake_genai).generate("gemini-2.5-flash", REQ, 1)
        assert e.value.kind == kind
        assert "key-one-secret" not in str(e.value)


async def test_gemini_other_failures_map_to_kinds(fake_genai):
    cases = [
        (api_error(404), "unavailable"),
        (api_error(403), "error"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("no net"), "unavailable"),
        (RuntimeError("weird"), "error"),
    ]
    for exc, kind in cases:
        fake_genai.next_error = exc
        with pytest.raises(ProviderError) as e:
            await gem(fake_genai).generate("gemini-2.5-flash", REQ, 1)
        assert e.value.kind == kind


async def test_gemini_attempt_timeout_maps_to_timeout(fake_genai):
    fake_genai.next_text = "hang"
    req = ProviderRequest("t", "sys", ["x"], SCHEMA, 0.2, 0.05)
    with pytest.raises(ProviderError) as e:
        await gem(fake_genai).generate("gemini-2.5-flash", req, 1)
    assert e.value.kind == "timeout"


async def test_gemini_sends_schema_temperature_and_jpeg_parts(fake_genai):
    out = await gem(fake_genai).generate("gemini-2.5-flash", REQ_WITH_IMAGE, 2)
    assert out == {"ok": True}
    cfg = fake_genai.last_config
    assert cfg.response_mime_type == "application/json" and cfg.temperature == 0.2
    assert fake_genai.last_key_slot == 2
    assert cfg.response_json_schema == SCHEMA and cfg.system_instruction == "sys"
    assert fake_genai.last_parts[0].text == "look"
    assert fake_genai.last_parts[1].inline_data.mime_type == "image/jpeg"
    assert fake_genai.last_parts[1].inline_data.data == b"\xff\xd8jpeg"
    assert cfg.http_options.timeout == 5000


async def test_gemini_minimal_thinking_per_model_family(fake_genai):
    await gem(fake_genai).generate("gemini-2.5-flash", REQ, 1)
    assert fake_genai.last_config.thinking_config.thinking_budget == 0
    await gem(fake_genai).generate("gemini-3.1-flash-lite", REQ, 1)
    tc = fake_genai.last_config.thinking_config
    assert str(tc.thinking_level.value) == "MINIMAL" and tc.thinking_budget is None


async def test_gemini_invalid_json_and_schema_violations_are_invalid_output(fake_genai):
    for text in ["not json", "[1, 2]", '{"ok": "yes"}', '{"nope": 1}', ""]:
        fake_genai.next_text = text
        with pytest.raises(ProviderError) as e:
            await gem(fake_genai).generate("gemini-2.5-flash", REQ, 1)
        assert e.value.kind == "invalid_output", text


async def test_gemini_missing_key_slot_is_unavailable(fake_genai):
    with pytest.raises(ProviderError) as e:
        await gem(fake_genai).generate("gemini-2.5-flash", REQ, 4)
    assert e.value.kind == "unavailable"
    with pytest.raises(ProviderError) as e:
        await gem(fake_genai).generate("gemini-2.5-flash", REQ, None)
    assert e.value.kind == "unavailable"


# ---- Ollama ------------------------------------------------------------------------------------------


def mock_ollama(capabilities=("completion", "vision"), chat_content='{"ok": true}', seen=None, tags=None):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if seen is not None:
            seen.append((request.url.path, body))
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": list(capabilities)})
        if request.url.path == "/api/tags":
            names = tags or ["gemma4:e4b", "gemma4:12b"]
            return httpx.Response(200, json={"models": [{"name": n} for n in names]})
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"role": "assistant", "content": chat_content}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_ollama_picks_smallest_gemma4(monkeypatch):
    monkeypatch.delenv("BCS_MODEL_OLLAMA", raising=False)
    assert OllamaProvider.pick_model(["qwen3.5:9b", "gemma4:12b", "gemma4:e4b"]) == "gemma4:e4b"
    assert OllamaProvider.pick_model(["gemma4:27b", "gemma4:12b"]) == "gemma4:12b"
    assert OllamaProvider.pick_model(["qwen3.5:9b"]) is None
    monkeypatch.setenv("BCS_MODEL_OLLAMA", "qwen3.5:9b")
    assert OllamaProvider.pick_model(["gemma4:e4b"]) == "qwen3.5:9b"


async def test_ollama_vision_role_on_model_without_vision_is_unavailable():
    p = OllamaProvider(transport=mock_ollama(capabilities=["completion"]))
    with pytest.raises(ProviderError) as e:
        await p.generate("gemma4:e4b", REQ_WITH_IMAGE, None)
    assert e.value.kind == "unavailable"
    assert p.vision is False


async def test_ollama_capabilities_and_chat_payload():
    seen: list = []
    p = OllamaProvider(transport=mock_ollama(seen=seen))
    assert await p.capabilities("gemma4:e4b") == {"completion", "vision"}
    out = await p.generate("gemma4:e4b", REQ_WITH_IMAGE, None)
    assert out == {"ok": True} and p.vision is True and p.reachable is True
    chat = next(b for path, b in seen if path == "/api/chat")
    assert chat["stream"] is False and chat["format"] == SCHEMA and chat["options"]["temperature"] == 0.2
    assert chat["messages"][0] == {"role": "system", "content": "sys"}
    user = chat["messages"][1]
    assert user["content"] == "look" and len(user["images"]) == 1


async def test_ollama_family_name_resolves_to_smallest_installed(monkeypatch):
    monkeypatch.delenv("BCS_MODEL_OLLAMA", raising=False)
    seen: list = []
    p = OllamaProvider(transport=mock_ollama(seen=seen))
    await p.generate("gemma4", REQ, None)
    assert next(b for path, b in seen if path == "/api/chat")["model"] == "gemma4:e4b"


async def test_ollama_errors_map_to_kinds():
    def boom(exc):
        def handler(request):
            raise exc

        return httpx.MockTransport(handler)

    p = OllamaProvider(transport=boom(httpx.ConnectError("down")))
    with pytest.raises(ProviderError) as e:
        await p.generate("gemma4:e4b", REQ, None)
    assert e.value.kind == "unavailable" and p.reachable is False
    p = OllamaProvider(transport=boom(httpx.ReadTimeout("slow")))
    with pytest.raises(ProviderError) as e:
        await p.generate("gemma4:e4b", REQ, None)
    assert e.value.kind == "timeout"
    for content in ["garbage", '{"ok": 3}']:
        p = OllamaProvider(transport=mock_ollama(chat_content=content))
        with pytest.raises(ProviderError) as e:
            await p.generate("gemma4:e4b", REQ, None)
        assert e.value.kind == "invalid_output"
    ok = mock_ollama()
    p = OllamaProvider(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(500) if r.url.path == "/api/chat" else ok.handler(r)
        )
    )
    with pytest.raises(ProviderError) as e:
        await p.generate("gemma4:e4b", REQ, None)
    assert e.value.kind == "overloaded"


# ---- Rules -------------------------------------------------------------------------------------------


class Out(BaseModel):
    ok: bool


class RuleRole:
    name = "r"

    def rules(self, inp: int) -> Out:
        return Out(ok=inp > 0)


def test_rules_provider_run_delegates_and_never_raises():
    rp = RulesProvider()
    assert rp.run(RuleRole(), 1) == Out(ok=True)

    class Bad(RuleRole):
        def rules(self, inp):
            raise RuntimeError("bug")

    assert rp.run(Bad(), 1) is None


async def test_rules_provider_generate_uses_bound_role():
    out = await RulesProvider.bound(RuleRole(), 5).generate("rules", REQ, None)
    assert out == {"ok": True}
    with pytest.raises(ProviderError) as e:
        await RulesProvider().generate("rules", REQ, None)
    assert e.value.kind == "unavailable"


async def test_ollama_family_name_recovers_when_ollama_starts_later(monkeypatch):
    monkeypatch.delenv("BCS_MODEL_OLLAMA", raising=False)
    up = mock_ollama()
    state = {"down": True}

    def handler(request):
        if state["down"]:
            raise httpx.ConnectError("down")
        return up.handler(request)

    p = OllamaProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as e:
        await p.generate("gemma4", REQ, None)
    assert e.value.kind == "unavailable"
    state["down"] = False
    assert await p.generate("gemma4", REQ, None) == {"ok": True}
    assert p.reachable is True


async def test_ollama_non_dict_show_response_is_error_kind():
    def handler(request):
        return httpx.Response(200, json=["not", "a", "dict"])

    p = OllamaProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as e:
        await p.generate("gemma4:e4b", REQ, None)
    assert e.value.kind == "error"
