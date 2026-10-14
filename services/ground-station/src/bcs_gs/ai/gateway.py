"""AIGateway (product spec section 17, addendum M): one per process.

A role call walks the role's tier chain from config/ai.yaml:

* **Cache first.** The newest valid success logged under the same cache key (role, versions, model,
  canonical inputs, image hashes) for any cloud tier of the chain answers the call, logged as a
  ``cache_hit`` row. Rules and local (Gemma) answers are never served from the cache, so a later call
  can still reach a cloud model; an OPERATOR call skips the cache read (its answer is still written).
* **Tiers in chain order.** A keyed tier (Gemini) tries key slots round-robin from the ``KeyRing``,
  skipping slots in cool-down or out of their per-(slot, model) token bucket, until one answers or none
  is left. ``rate_limited``, ``overloaded`` and key-scoped ``error`` (HTTP 401/403, invalid API key) cool
  the slot down and try the next one; ``timeout`` cools the slot down and moves to the next tier (a slow
  network would make every key time out); ``invalid_output``, ``unavailable`` and other ``error`` move
  straight to the next tier.
* **Budget.** Each attempt is limited to its tier's timeout (text 20 s, vision 30 s, local 60 s) and to
  what is left of the 60 s role budget, which is checked between attempts; once it is spent every
  remaining tier is skipped and rules answer. While a local tier follows later in the chain, cloud tiers
  leave it ``local_reserve`` seconds (20 s) of the budget.
* **Validation.** ``role.check(output_model.model_validate(raw), inp)``; a ``ValidationError`` or
  ``OutputRejected`` is ``invalid_output``.
* **Rules** (``role.rules(inp)``) always answer last and cannot fail.
* **Log.** Every attempt, skipped tier and cache hit is one ``ai_calls`` row (``fallback_from`` links it
  to the previous row of the same call) and one ``ai.call`` event. Key values never appear: only the
  slot number, and error text is masked against every registered secret.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Generic

from bcs_protocol.timefmt import to_iso
from pydantic import BaseModel, ValidationError

from bcs_gs.ai.budget import TokenBucket
from bcs_gs.ai.cache import cache_key, canonical_json, request_inputs, sha256_hex
from bcs_gs.ai.keys import KeyRing
from bcs_gs.ai.providers.base import AIProvider, ProviderError, ProviderRequest
from bcs_gs.ai.queue import PriorityGate
from bcs_gs.ai.roles.base import O, OutputRejected, Priority, Role
from bcs_gs.api.models import AIKeyStatus, AIRoleStatus, AIStatus, OllamaStatus, SourceChip
from bcs_gs.core.aio import to_thread_settled
from bcs_gs.core.clock import Clock
from bcs_gs.core.config import AI
from bcs_gs.core.events import EventBus
from bcs_gs.core.ids import uuid7
from bcs_gs.core.logging import mask_secrets
from bcs_gs.store.repo import Repo

log = logging.getLogger(__name__)

KEYED_PROVIDERS = frozenset({"gemini"})  # providers whose attempts use a key slot
# Key-scoped failures: cool the slot down and try the next key. ``error`` counts only when it names the
# key (HTTP 401/403, "API key not valid"); a request-scoped error (e.g. an oversized input) would fail on
# every key, so it moves to the next tier. ``timeout`` cools the slot but moves to the next tier.
ROTATE_KINDS = frozenset({"rate_limited", "overloaded"})
_KEY_ERROR = re.compile(
    r"\b(?:HTTP )?40[13]\b|api[ _]?key|unauthenticated|permission[ _]denied", re.IGNORECASE
)
# Every gate has room for at least 2 so that PriorityGate's reserved slot applies: a background call
# never holds the only slot of a tier (e.g. Gemma while offline) against an operator call.
MIN_GATE_CAPACITY = 2
DEGRADED_PROVIDERS = frozenset({"ollama", "rules"})  # answered without a cloud model
# local_reserve: the budget a cloud tier leaves for a later local tier (Gemma ~19 s cold on the laptop)
DEFAULT_TIMEOUTS = {"text": 20.0, "vision": 30.0, "local": 60.0, "role_budget": 60.0, "local_reserve": 20.0}
_ERROR_MAX = 300
_WAIT_GRACE_S = 5.0  # safety net over a provider's own timeout


@dataclass(frozen=True)
class TierCfg:
    name: str
    provider: str  # "gemini" | "ollama" | "rules" | ...
    model: str | None
    label: str = ""
    factor: float | None = None

    @staticmethod
    def from_settings(ai: AI) -> dict[str, TierCfg]:
        return {
            name: TierCfg(
                name=name,
                provider=str(cfg["provider"]),
                model=None if cfg["provider"] == "rules" else ai.models.get(name),
                label=str(cfg.get("label") or name),
                factor=cfg.get("factor"),
            )
            for name, cfg in ai.tiers.items()
        }


@dataclass
class RoleResult(Generic[O]):
    output: O
    source: SourceChip
    call_id: str  # the ai_calls row that answered (the cache_hit row for a cached answer)
    request_id: str  # groups every row of this call
    attempts: int  # ai_calls rows written by this call (attempts, skipped tiers, cache hit)
    elapsed_s: float = 0.0
    status: str = "success"  # "success" | "cache_hit"


@dataclass
class _Call:
    role: Any
    inp: Any
    priority: Priority
    request_id: str
    started: float
    inputs: dict[str, Any]
    image_refs: list[str]
    image_hashes: list[str]
    input_hash: str
    prev: str | None = None
    reserve: float = 0.0  # seconds of the role budget kept for a later local tier
    last_error: str | None = None  # the error text of the latest failed attempt
    attempts: int = 0
    rows: list[str] = field(default_factory=list)


class AIGateway:
    def __init__(
        self,
        providers: Mapping[str, AIProvider],
        chains: Mapping[str, list[str]],
        tiers: Mapping[str, TierCfg],
        repo: Repo,
        clock: Clock,
        bus: EventBus,
        *,
        key_slots: Sequence[int] = (1, 2, 3),
        timeouts: Mapping[str, float] | None = None,
        cooldown_s: float = 60,
        cooldown_max_s: float = 600,
        backoff: float = 2,
        rate_per_min: float = 5,
    ) -> None:
        self.providers = dict(providers)
        self.tiers = dict(tiers)
        self.chains: dict[str, list[str]] = {}
        for role, chain in chains.items():
            unknown = [t for t in chain if t not in self.tiers]
            if unknown:
                raise ValueError(f"chain {role!r} names unknown tiers: {unknown}")
            # rules is always last (and always present)
            rules = [t for t in chain if self.tiers[t].provider == "rules"] or ["rules"]
            self.chains[role] = [t for t in chain if self.tiers[t].provider != "rules"] + rules[-1:]
        if "rules" not in self.tiers:
            self.tiers["rules"] = TierCfg("rules", "rules", None, "Rules")
        self.repo = repo
        self.clock = clock
        self.bus = bus
        self.timeouts = {**DEFAULT_TIMEOUTS, **(timeouts or {})}
        self.keyring = KeyRing(
            list(key_slots), clock, cooldown_s=cooldown_s, cooldown_max_s=cooldown_max_s, backoff=backoff
        )
        self._rate = rate_per_min
        self._buckets: dict[tuple[int, str], TokenBucket] = {}
        self._gates = {
            name: PriorityGate(
                max(MIN_GATE_CAPACITY, len(self.keyring.slots))
                if t.provider in KEYED_PROVIDERS
                else MIN_GATE_CAPACITY
            )
            for name, t in self.tiers.items()
            if t.provider != "rules"
        }
        self._last: dict[str, tuple[str, str, str]] = {}  # role -> (tier, status, at) of the last answer
        self._daily_day: str | None = None
        self._daily: dict[str, int] = {}
        self._last_at: datetime | None = None

    @classmethod
    def from_settings(
        cls,
        ai: AI,
        providers: Mapping[str, AIProvider],
        repo: Repo,
        clock: Clock,
        bus: EventBus,
        *,
        key_slots: Sequence[int] = (1, 2, 3),
    ) -> AIGateway:
        kr = ai.key_rotation
        return cls(
            providers,
            ai.chains,
            TierCfg.from_settings(ai),
            repo,
            clock,
            bus,
            key_slots=key_slots,
            timeouts=ai.timeouts_s,
            cooldown_s=kr.get("cooldown_s", 60),
            cooldown_max_s=kr.get("cooldown_max_s", 600),
            backoff=kr.get("backoff_factor", 2),
            rate_per_min=ai.rate.get("requests_per_min", 5),
        )

    # -- accessors ------------------------------------------------------------------------------
    def provider(self, name: str) -> AIProvider:
        return self.providers[name]

    def bucket(self, slot: int, model: str) -> TokenBucket:
        key = (slot, model)
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(self._rate, self.clock)
        return self._buckets[key]

    # -- the call -------------------------------------------------------------------------------
    async def call(self, role: Role[Any, O], inp: Any, priority: Priority) -> RoleResult[O]:
        chain = self.chains.get(role.name)
        if chain is None:
            raise ValueError(f"no tier chain configured for role {role.name!r}")
        req = role.request(inp)
        inputs, image_hashes = request_inputs(req)
        c = _Call(
            role=role,
            inp=inp,
            priority=priority,
            request_id=uuid7(),
            started=self.clock.monotonic(),
            inputs=inputs,
            image_refs=[f"sha256:{h}" for h in image_hashes],
            image_hashes=image_hashes,
            input_hash=sha256_hex(canonical_json({"inputs": inputs, "image_hashes": image_hashes})),
        )
        model_tiers = [self.tiers[t] for t in chain if self.tiers[t].provider != "rules"]

        if priority != Priority.OPERATOR:  # an operator asks for a fresh answer
            cached = await self._from_cache(c, model_tiers)
            if cached is not None:
                return cached

        for i, tier in enumerate(model_tiers):
            c.reserve = self._reserve(tier, model_tiers[i + 1 :])
            if self._remaining(c) - c.reserve <= 0:
                why = "role budget reserved for the local tier" if c.reserve else "role budget exhausted"
                await self._log(c, tier, status="skipped", error=why)
                continue
            provider = self.providers.get(tier.provider)
            if provider is None:
                await self._log(c, tier, status="skipped", error=f"no {tier.provider} provider configured")
                continue
            result = await self._run_tier(c, tier, provider, req)
            if result is not None:
                return result

        rules_tier = self.tiers[chain[-1]]
        out = role.rules(inp)
        row_id = await self._log(
            c, rules_tier, status="success", output=out.model_dump(mode="json"), valid=True, latency_ms=0
        )
        return self._result(c, rules_tier, out, row_id, cached=False)

    async def _from_cache(self, c: _Call, model_tiers: list[TierCfg]) -> RoleResult | None:
        role = c.role
        for tier in model_tiers:
            if tier.provider in DEGRADED_PROVIDERS:
                continue  # a local answer is not kept once a cloud model can answer again
            key = self._cache_key(c, tier)
            rows = await asyncio.to_thread(
                self.repo.query,
                "SELECT * FROM ai_calls WHERE cache_key = ? AND status = 'success' AND valid = 1 "
                "ORDER BY at DESC LIMIT 1",
                (key,),
                table="ai_calls",
            )
            if not rows:
                continue
            try:
                out = role.check(role.output_model.model_validate(rows[0]["output"]), c.inp)
            except (ValidationError, OutputRejected):
                continue  # a stale entry the current checks reject: not a hit
            row_id = await self._log(
                c,
                tier,
                status="cache_hit",
                output=rows[0]["output"],
                valid=True,
                latency_ms=0,
                cache_hit=True,
            )
            return self._result(c, tier, out, row_id, cached=True)
        return None

    async def _run_tier(
        self, c: _Call, tier: TierCfg, provider: AIProvider, req: ProviderRequest
    ) -> RoleResult | None:
        gate = self._gates[tier.name]
        try:
            await asyncio.wait_for(
                gate.acquire(c.priority), timeout=max(0.001, self._remaining(c) - c.reserve)
            )
        except TimeoutError:
            await self._log(c, tier, status="skipped", error="waited past the role budget")
            return None
        try:
            if tier.provider not in KEYED_PROVIDERS:
                _, out = await self._attempt(c, tier, provider, req, None)
                return out
            model = tier.model or ""
            tried: set[int] = set()
            attempted = False
            while True:
                if attempted and self._remaining(c) - c.reserve <= 0:
                    return None  # budget spent between attempts: the remaining tiers are skipped
                slot = self.keyring.next_available(model, exclude=tried)
                if slot is None:
                    if not attempted:
                        await self._log(
                            c,
                            tier,
                            status="skipped",
                            error="no key available (cooling down or over the rate budget)",
                        )
                    return None
                tried.add(slot)
                if not self.bucket(slot, model).try_take():
                    continue
                attempted = True
                status, out = await self._attempt(c, tier, provider, req, slot)
                if out is not None:
                    self.keyring.reset(slot, model)
                    return out
                if status in ROTATE_KINDS or (status == "error" and _key_scoped(c.last_error)):
                    self.keyring.cooldown(slot, model)
                    continue
                if status == "timeout":
                    self.keyring.cooldown(slot, model)  # slow network: the next key would time out too
                return None
        finally:
            gate.release()

    async def _attempt(
        self, c: _Call, tier: TierCfg, provider: AIProvider, req: ProviderRequest, slot: int | None
    ) -> tuple[str, RoleResult | None]:
        role = c.role
        timeout = max(0.001, min(self._attempt_timeout(tier, req), self._remaining(c) - c.reserve))
        sent = dataclasses.replace(req, timeout_s=timeout)
        self._count_daily(tier.model or tier.provider)
        t0 = self.clock.monotonic()
        raw: Any = None
        out: BaseModel | None = None
        error: str | None = None
        valid: bool | None = None
        try:
            raw = await asyncio.wait_for(
                provider.generate(tier.model or "", sent, slot), timeout + _WAIT_GRACE_S
            )
        except ProviderError as e:
            status, error = e.kind, e.detail or None
        except TimeoutError:
            status, error = "timeout", f"no answer within {timeout:.0f} s"
        except Exception as e:  # noqa: BLE001 (a provider bug must not break the chain)
            status, error = "error", f"{type(e).__name__}: {e}"
        else:
            try:
                if not isinstance(raw, dict):
                    raise OutputRejected(f"output is {type(raw).__name__}, not an object")
                out = role.check(role.output_model.model_validate(raw), c.inp)
                status, valid = "success", True
            except (ValidationError, OutputRejected) as e:
                status, valid, error = "invalid_output", False, f"{type(e).__name__}: {e}"
        latency_ms = round((self.clock.monotonic() - t0) * 1000)
        c.last_error = error
        row_id = await self._log(
            c,
            tier,
            status=status,
            key_slot=slot,
            output=_jsonable(raw),
            valid=valid,
            latency_ms=latency_ms,
            error=error,
        )
        if out is None:
            return status, None
        return status, self._result(c, tier, out, row_id, cached=False)

    # -- helpers ---------------------------------------------------------------------------------
    def _remaining(self, c: _Call) -> float:
        return self.timeouts["role_budget"] - (self.clock.monotonic() - c.started)

    def _reserve(self, tier: TierCfg, later: list[TierCfg]) -> float:
        """Budget kept back from a cloud tier for a later local tier whose provider is configured."""
        if tier.provider in DEGRADED_PROVIDERS:
            return 0.0
        if any(t.provider == "ollama" and t.provider in self.providers for t in later):
            return self.timeouts["local_reserve"]
        return 0.0

    def _attempt_timeout(self, tier: TierCfg, req: ProviderRequest) -> float:
        if tier.provider == "ollama":
            return self.timeouts["local"]
        if any(isinstance(p, bytes | bytearray) for p in req.parts):
            return self.timeouts["vision"]
        return self.timeouts["text"]

    def _cache_key(self, c: _Call, tier: TierCfg) -> str:
        r = c.role
        return cache_key(r.name, r.schema_version, r.prompt_version, tier.model, c.inputs, c.image_hashes)

    def _count_daily(self, model: str) -> None:
        day = self.clock.now().date().isoformat()
        if day != self._daily_day:
            self._daily_day, self._daily = day, {}
        self._daily[model] = self._daily.get(model, 0) + 1

    def _next_at(self) -> datetime:
        """Now, truncated to milliseconds and strictly after the previous row's ``at``, so that
        ordering ``ai_calls`` by ``at`` is the attempt order even when the clock stands still."""
        now = self.clock.now()
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
        if self._last_at is not None and now <= self._last_at:
            now = self._last_at + timedelta(milliseconds=1)
        self._last_at = now
        return now

    def _result(self, c: _Call, tier: TierCfg, out: Any, row_id: str, *, cached: bool) -> RoleResult:
        status = "cache_hit" if cached else "success"
        self._last[c.role.name] = (tier.name, status, to_iso(self.clock.now()))
        return RoleResult(
            output=out,
            source=SourceChip(tier=tier.name, model=tier.model, cached=cached, ai_call_id=row_id),
            call_id=row_id,
            request_id=c.request_id,
            attempts=c.attempts,
            elapsed_s=self.clock.monotonic() - c.started,
            status=status,
        )

    async def _log(
        self,
        c: _Call,
        tier: TierCfg,
        *,
        status: str,
        key_slot: int | None = None,
        output: Any = None,
        valid: bool | None = None,
        latency_ms: int | None = None,
        error: str | None = None,
        cache_hit: bool = False,
    ) -> str:
        role = c.role
        row = {
            "id": uuid7(),
            "request_id": c.request_id,
            "at": to_iso(self._next_at()),
            "role": role.name,
            "tier": tier.name,
            "provider": tier.provider,
            "model": tier.model,
            "key_slot": key_slot,
            "prompt_version": role.prompt_version,
            "schema_version": role.schema_version,
            "input_hash": c.input_hash,
            "cache_key": self._cache_key(c, tier),
            "inputs": c.inputs,
            "image_refs": c.image_refs,
            "output": output,
            "valid": valid,
            "latency_ms": latency_ms,
            "status": status,
            "error": None if error is None else mask_secrets(error)[:_ERROR_MAX],
            "fallback_from": c.prev,
            "cache_hit": cache_hit,
        }
        try:
            await to_thread_settled(self.repo.insert, "ai_calls", row)  # a cancel leaves no write behind
        except Exception as e:  # noqa: BLE001 (a failed log write must not cost the caller its answer)
            log.warning("ai_calls write failed for %s (%s): %s", role.name, status, type(e).__name__)
        c.prev = row["id"]
        c.attempts += 1
        c.rows.append(row["id"])
        payload = {
            k: row[k]
            for k in (
                "id",
                "request_id",
                "at",
                "role",
                "tier",
                "provider",
                "model",
                "key_slot",
                "prompt_version",
                "status",
                "latency_ms",
                "cache_hit",
                "valid",
                "error",
                "fallback_from",
            )
        }
        self.bus.publish("ai.call", {"call_id": row["id"], **payload, "cached": cache_hit})
        if status not in ("success", "cache_hit"):
            log.info("ai %s tier=%s slot=%s status=%s", role.name, tier.name, key_slot, status)
        return row["id"]

    # -- status (I3 AIStatus) --------------------------------------------------------------------
    def status(self) -> AIStatus:
        roles: dict[str, AIRoleStatus] = {}
        for name in sorted({*self.chains, *self._last}):
            last = self._last.get(name)
            if last is None:
                roles[name] = AIRoleStatus(degraded=False)
            else:
                tier, status, at = last
                roles[name] = AIRoleStatus(
                    last_tier=tier,
                    last_status=status,
                    last_at=at,
                    degraded=self.tiers[tier].provider in DEGRADED_PROVIDERS,
                )
        used = {t for chain in self.chains.values() for t in chain}
        models = sorted(
            {
                self.tiers[t].model
                for t in used
                if self.tiers[t].provider in KEYED_PROVIDERS and self.tiers[t].model
            }
        )
        now = self.clock.now()
        keys = []
        for model in models:
            for slot in self.keyring.slots:
                rem = self.keyring.cooldown_remaining(slot, model)
                keys.append(
                    AIKeyStatus(
                        slot=slot,
                        model=model,
                        state="cooldown" if rem > 0 else "ok",
                        cooldown_until=to_iso(now + timedelta(seconds=rem)) if rem > 0 else None,
                        tokens=int(self.bucket(slot, model).tokens + 1e-9),
                    )
                )
        day = now.date().isoformat()
        daily = dict(self._daily) if day == self._daily_day else {}
        local = next((t for t in self.tiers.values() if t.provider == "ollama"), None)
        ollama = self.providers.get("ollama")
        return AIStatus(
            roles=roles,
            keys=keys,
            daily=daily,
            ollama=OllamaStatus(
                model=local.model if local else None,
                vision=bool(getattr(ollama, "vision", False)),
                reachable=bool(getattr(ollama, "reachable", False)),
            ),
        )


def _key_scoped(error: str | None) -> bool:
    """An ``error`` that names the key (HTTP 401/403, invalid API key), not the request."""
    return bool(error and _KEY_ERROR.search(error))


def _jsonable(raw: Any) -> Any:
    """``raw`` when it can be stored as JSON (finite numbers only), else None."""
    if raw is None:
        return None
    try:
        canonical_json(raw)
    except (TypeError, ValueError):
        return None
    return raw
