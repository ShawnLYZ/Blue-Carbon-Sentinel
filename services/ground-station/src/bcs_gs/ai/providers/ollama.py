"""Local Ollama provider (gemma4): /api/chat with a JSON-schema ``format``."""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import httpx
import jsonschema

from bcs_gs.ai.providers.base import ProviderError, ProviderRequest

FAMILY = "gemma4"


def _size(name: str) -> float:
    """Parameter count (billions) from a tag like ``gemma4:e4b`` or ``gemma4:12b``; unknown sorts last."""
    m = re.search(r":e?(\d+(?:\.\d+)?)b", name)
    return float(m.group(1)) if m else float("inf")


class OllamaProvider:
    provider = "ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        connect_timeout_s: float = 3.0,
    ) -> None:
        self.base_url = base_url
        self._transport = transport
        self._connect_timeout_s = connect_timeout_s
        self.vision: bool = False  # does the model last used accept images (read by AIGateway.status)
        self.reachable: bool = False  # did the last request reach the server
        self._caps: dict[str, set[str]] = {}
        self._installed: list[str] | None = None

    def _http(self, timeout_s: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            transport=self._transport,
            timeout=httpx.Timeout(timeout_s, connect=self._connect_timeout_s),
        )

    @staticmethod
    def pick_model(available: list[str]) -> str | None:
        """``BCS_MODEL_OLLAMA`` if set; else the smallest ``gemma4`` variant by parameter count."""
        override = os.environ.get("BCS_MODEL_OLLAMA")
        if override:
            return override
        gemma = [n for n in available if n.split(":")[0] == FAMILY]
        return min(gemma, key=_size) if gemma else None

    async def installed(self) -> list[str]:
        """Names of the installed models (``/api/tags``); an unreachable server gives ``[]``."""
        try:
            async with self._http(5) as c:
                r = await c.get("/api/tags")
            r.raise_for_status()
            self.reachable = True
            names = [m["name"] for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            self.reachable = False
            self._installed = None  # never cache a failed listing: Ollama may start later
            return []
        self._installed = names
        return names

    async def capabilities(self, model: str) -> set[str]:
        """``/api/show`` capabilities of ``model`` (e.g. ``completion``, ``vision``), cached."""
        if model not in self._caps:
            try:
                async with self._http(10) as c:
                    r = await c.post("/api/show", json={"model": model})
                r.raise_for_status()
                self.reachable = True
                self._caps[model] = set(r.json().get("capabilities", []))
            except httpx.HTTPStatusError as e:
                self.reachable = True
                raise ProviderError("unavailable", f"/api/show {e.response.status_code}") from None
            except httpx.TimeoutException:
                raise ProviderError("timeout", "/api/show timed out") from None
            except (httpx.HTTPError, ValueError) as e:
                self.reachable = False
                raise ProviderError("unavailable", f"ollama unreachable ({type(e).__name__})") from None
            except (TypeError, AttributeError, KeyError):
                raise ProviderError("error", "unexpected /api/show response") from None
        return self._caps[model]

    async def _resolve(self, model: str) -> str:
        """A bare family name from config (``gemma4``) becomes the smallest installed variant."""
        if ":" in model and not os.environ.get("BCS_MODEL_OLLAMA"):
            return model
        names = self._installed or await self.installed()  # re-list while the cache is empty
        picked = self.pick_model(names)
        if picked is None:
            if not self.reachable:
                raise ProviderError("unavailable", "ollama unreachable")
            raise ProviderError("unavailable", "no gemma4 model installed")
        return picked

    async def generate(self, model: str, req: ProviderRequest, key_slot: int | None) -> dict:
        model = await self._resolve(model)
        images = [p for p in req.parts if isinstance(p, bytes)]
        caps = await self.capabilities(model)
        self.vision = "vision" in caps
        if images and not self.vision:
            raise ProviderError("unavailable", f"{model} has no vision capability")
        user: dict[str, Any] = {
            "role": "user",
            "content": "\n\n".join(p for p in req.parts if isinstance(p, str)),
        }
        if images:
            user["images"] = [base64.b64encode(p).decode("ascii") for p in images]
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": req.system}, user],
            "stream": False,
            "format": req.response_schema,
            "options": {"temperature": req.temperature},
        }
        try:
            async with self._http(req.timeout_s) as c:
                r = await c.post("/api/chat", json=payload)
            self.reachable = True
        except httpx.TimeoutException:
            raise ProviderError("timeout", f"no answer in {req.timeout_s:g}s") from None
        except httpx.HTTPError as e:
            self.reachable = False
            raise ProviderError("unavailable", f"ollama unreachable ({type(e).__name__})") from None
        if r.status_code == 404:
            raise ProviderError("unavailable", f"model {model} not installed")
        if r.status_code >= 500 or r.status_code == 429:
            raise ProviderError("overloaded", f"ollama HTTP {r.status_code}")
        if r.status_code >= 400:
            raise ProviderError("error", f"ollama HTTP {r.status_code}")
        try:
            out = json.loads(r.json()["message"]["content"])
        except (ValueError, KeyError, TypeError):
            raise ProviderError("invalid_output", "response is not JSON") from None
        if not isinstance(out, dict):
            raise ProviderError("invalid_output", "response is not a JSON object")
        try:
            jsonschema.validate(out, req.response_schema)
        except jsonschema.ValidationError as e:
            raise ProviderError("invalid_output", f"schema: {e.message[:200]}") from None
        except jsonschema.SchemaError:
            pass
        return out
