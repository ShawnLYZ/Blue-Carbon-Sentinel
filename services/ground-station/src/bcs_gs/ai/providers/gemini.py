"""Gemini Developer API provider (google-genai): structured JSON, one key slot per attempt."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import jsonschema
from google import genai
from google.genai import errors, types
from pydantic import SecretStr

from bcs_gs.ai.providers.base import ErrorKind, ProviderError, ProviderRequest
from bcs_gs.core.logging import mask_secrets

DEFAULT_HTTP_TIMEOUT_S = 30.0


def thinking_config(model: str) -> types.ThinkingConfig:
    """The lowest thinking the model accepts: budget 0 for the 2.5 family, level MINIMAL for 3.x."""
    if "2.5" in model:
        return types.ThinkingConfig(thinking_budget=0)
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)


def kind_for_status(code: int) -> ErrorKind:
    if code == 429:
        return "rate_limited"
    if code in (500, 502, 503):
        return "overloaded"
    if code in (408, 504):
        return "timeout"
    if code in (404, 410):
        return "unavailable"  # unknown model id: skip the tier
    return "error"  # 400 / 401 / 403 ...: bad request or bad key


class GeminiProvider:
    provider = "gemini"

    def __init__(
        self,
        keys: dict[int, SecretStr],
        http_timeout_s: float = DEFAULT_HTTP_TIMEOUT_S,
        *,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._keys = keys
        self._http_timeout_s = http_timeout_s
        self._factory = client_factory or self._default_factory
        self._clients: dict[int, Any] = {}

    def _default_factory(self, api_key: str) -> Any:
        opts = types.HttpOptions(timeout=int(self._http_timeout_s * 1000))
        return genai.Client(api_key=api_key, http_options=opts)

    def _client(self, slot: int | None) -> Any:
        key = self._keys.get(slot) if slot is not None else None
        if slot is None or key is None or not key.get_secret_value():
            raise ProviderError("unavailable", f"no Gemini key in slot {slot}")
        if slot not in self._clients:
            self._clients[slot] = self._factory(key.get_secret_value())
        return self._clients[slot]

    def _clean(self, text: str) -> str:
        for k in self._keys.values():
            if k.get_secret_value():
                text = text.replace(k.get_secret_value(), "***")
        return mask_secrets(text)[:300]

    async def generate(self, model: str, req: ProviderRequest, key_slot: int | None) -> dict:
        client = self._client(key_slot)
        parts: list[types.Part] = [
            types.Part.from_bytes(data=p, mime_type="image/jpeg")
            if isinstance(p, bytes)
            else types.Part(text=p)
            for p in req.parts
        ]
        config = types.GenerateContentConfig(
            system_instruction=req.system or None,
            temperature=req.temperature,
            response_mime_type="application/json",
            response_json_schema=req.response_schema,
            thinking_config=thinking_config(model),
            http_options=types.HttpOptions(timeout=int(req.timeout_s * 1000)),
        )
        try:
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(model=model, contents=parts, config=config),
                timeout=req.timeout_s,
            )
        except TimeoutError as e:  # asyncio.wait_for
            raise ProviderError("timeout", f"no answer in {req.timeout_s:g}s") from e
        except errors.APIError as e:
            code = int(getattr(e, "code", 0) or 0)
            raise ProviderError(kind_for_status(code), self._clean(f"HTTP {code} {e}")) from None
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", type(e).__name__) from None
        except (httpx.TransportError, OSError) as e:
            raise ProviderError("unavailable", self._clean(f"{type(e).__name__}: {e}")) from None
        except Exception as e:  # noqa: BLE001 - never leak a key through an SDK exception message
            raise ProviderError("error", self._clean(f"{type(e).__name__}: {e}")) from None
        return self._parse(resp, req)

    @staticmethod
    def _parse(resp: Any, req: ProviderRequest) -> dict:
        text = getattr(resp, "text", None)
        if not text:
            raise ProviderError("invalid_output", "empty response")
        try:
            out = json.loads(text)
        except ValueError:
            raise ProviderError("invalid_output", "response is not JSON") from None
        if not isinstance(out, dict):
            raise ProviderError("invalid_output", "response is not a JSON object")
        try:
            jsonschema.validate(out, req.response_schema)
        except jsonschema.ValidationError as e:
            raise ProviderError("invalid_output", f"schema: {e.message[:200]}") from None
        except jsonschema.SchemaError:
            pass  # a role schema jsonschema cannot interpret: the role's own check still runs
        return out
