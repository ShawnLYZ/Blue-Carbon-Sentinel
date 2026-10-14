"""AIGateway core (M4 Task 1): tier chains, key rotation and cool-down, budgets, cache, validation,
the ``ai_calls`` log and its JSONL export. Providers are FakeProviders on a ManualClock."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from bcs_gs.ai.budget import TokenBucket
from bcs_gs.ai.cache import cache_key
from bcs_gs.ai.export import export_jsonl
from bcs_gs.ai.gateway import AIGateway, RoleResult
from bcs_gs.ai.providers.base import ProviderError, ProviderRequest
from bcs_gs.ai.providers.fake import FakeProvider
from bcs_gs.ai.queue import PriorityGate
from bcs_gs.ai.roles.base import OutputRejected, Priority
from bcs_gs.core.clock import ManualClock
from bcs_gs.core.config import AI
from bcs_gs.core.events import EventBus
from bcs_gs.core.logging import register_secret
from bcs_gs.store.db import Database
from bcs_gs.store.repo import Repo
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[4]
T0 = datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)


class _Out(BaseModel):
    multiplier: float = Field(ge=0.5, le=1.5)
    narrative: str


class _TestRole:
    """A tiny text role on the risk_interpreter chain. ``check`` rejects the word "override"."""

    name = "risk_interpreter"
    schema_version = "1"
    prompt_version = "test-1"
    output_model = _Out

    def request(self, inp: dict[str, Any]) -> ProviderRequest:
        return ProviderRequest(
            role=self.name,
            system="You interpret risk.",
            parts=[f"zone {inp['zone']} stress {inp['stress']}"],
            response_schema=_Out.model_json_schema(),
            temperature=0.2,
            timeout_s=20,
        )

    def check(self, out: _Out, inp: dict[str, Any]) -> _Out:
        if "override" in out.narrative:
            raise OutputRejected("narrative tries to override code numbers")
        return out

    def rules(self, inp: dict[str, Any]) -> _Out:
        return _Out(multiplier=1.0, narrative=f"Rules: zone {inp['zone']}")


ROLE = _TestRole()
INPUT = {"zone": "KSL-B3", "stress": 0.42}
VALID_OUTPUT = {"multiplier": 1.2, "narrative": "Sediment is the main stressor."}
KEY_VALUES = ["AIzaSy-test-key-value-one", "AIzaSy-test-key-value-two", "AIzaSy-test-key-value-three"]


def _ai_config() -> AI:
    return AI.model_validate(yaml.safe_load((REPO_ROOT / "config" / "ai.yaml").read_text(encoding="utf-8")))


def _make_gw(tmp_path: Path) -> AIGateway:
    clock = ManualClock(T0)
    db = Database(tmp_path / "bcs.sqlite3", clock)
    db.migrate()
    providers = {
        "gemini": FakeProvider([], clock=clock, provider="gemini"),
        "ollama": FakeProvider([], clock=clock, provider="ollama"),
    }
    return AIGateway.from_settings(_ai_config(), providers, Repo(db), clock, EventBus(clock))


@pytest.fixture
def gw(tmp_path: Path) -> AIGateway:
    return _make_gw(tmp_path)


@pytest.fixture
async def gw_with_calls(tmp_path: Path) -> SimpleNamespace:
    """A gateway whose log holds successes, failures whose provider error text leaks a key value,
    a cache hit and a rules answer."""
    for k in KEY_VALUES:
        register_secret(k)
    g = _make_gw(tmp_path)
    g.provider("gemini").script = [
        ProviderError("rate_limited", f"429 for key={KEY_VALUES[0]}"),
        ProviderError("error", f"400 API key not valid: {KEY_VALUES[1]}"),
        VALID_OUTPUT,
    ]
    g.provider("ollama").script = [ProviderError("unavailable", f"refused {KEY_VALUES[2]}")]
    await g.call(ROLE, INPUT, Priority.FLAGGED)  # rate_limited (slot 1), error (slot 2), success (slot 3)
    await g.call(ROLE, INPUT, Priority.FLAGGED)  # cache hit (an OPERATOR call skips the cache read)
    await g.call(ROLE, {"zone": "KSL-A1", "stress": 0.1}, Priority.BACKGROUND)  # all unavailable -> rules
    return SimpleNamespace(repo=g.repo, key_values=KEY_VALUES, gw=g)


# ---- brief tests ------------------------------------------------------------------------------
async def test_tier_order_and_fallback_logging(gw):
    gw.provider("gemini").script = [ProviderError("overloaded")] * 3 + [ProviderError("rate_limited")] * 3
    gw.provider("ollama").script = [ProviderError("unavailable")]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "rules"
    calls = gw.repo.query("select tier, status, fallback_from from ai_calls order by at", ())
    assert [c["tier"] for c in calls][-1] == "rules" and calls[-1]["fallback_from"] is not None


async def test_key_rotation_round_robin_and_cooldown_doubling(gw):
    ring = gw.keyring
    m = "gemini-2.5-flash"
    assert [ring.next_available(m) for _ in range(3)] == [1, 2, 3]
    ring.cooldown(1, m)
    gw.clock.advance(59)
    assert ring.next_available(m) in (2, 3)
    gw.clock.advance(1)
    ring.cooldown(1, m)  # second strike -> 120 s
    gw.clock.advance(119)
    assert 1 not in {ring.next_available(m) for _ in range(4)}


async def test_all_keys_cooling_skips_tier_without_waiting(gw):  # Review Focus 1
    for s in (1, 2, 3):
        gw.keyring.cooldown(s, "gemini-2.5-flash")
        gw.keyring.cooldown(s, "gemini-3.1-flash-lite")
    started = gw.clock.monotonic()
    r = await gw.call(ROLE, INPUT, Priority.OPERATOR)
    assert r.source.tier in ("gemma_local", "rules") and gw.clock.monotonic() - started < 1


async def test_budget_five_per_minute_per_key_model(gw):
    b = TokenBucket(5, gw.clock)
    assert [b.try_take() for _ in range(6)] == [True] * 5 + [False]
    gw.clock.advance(12)
    assert b.try_take() is True


async def test_cache_hit_returns_cached_chip_and_logs_cache_hit(gw):
    gw.provider("gemini").script = [VALID_OUTPUT]
    a = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    b = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert a.source.cached is False and b.source.cached is True and b.source.tier == a.source.tier
    assert gw.repo.query("select count(*) n from ai_calls where status='cache_hit'", ())[0]["n"] == 1


async def test_invalid_json_moves_to_next_tier(gw):
    gw.provider("gemini").script = [ProviderError("invalid_output")] * 6
    gw.provider("ollama").script = [VALID_OUTPUT]
    assert (await gw.call(ROLE, INPUT, Priority.FLAGGED)).source.tier == "gemma_local"


async def test_role_budget_60s_then_next_tier(gw):
    gw.provider("gemini").script = [ProviderError("timeout")] * 6  # each attempt consumes its 20 s timeout
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier in ("gemma_local", "rules") and r.elapsed_s <= 60


def test_export_jsonl_never_contains_key_values(gw_with_calls):
    text = "\n".join(export_jsonl(gw_with_calls.repo, {}))
    for k in gw_with_calls.key_values:
        assert k not in text
    assert all(json.loads(line)["key_slot"] in (None, 1, 2, 3) for line in text.splitlines())


# ---- additional pins --------------------------------------------------------------------------
async def test_success_chip_ids_and_fake_records_requests(gw):
    gw.provider("gemini").script = [VALID_OUTPUT]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert isinstance(r, RoleResult)
    assert r.output == _Out(**VALID_OUTPUT)
    assert (r.source.tier, r.source.model, r.source.cached) == ("gemini_primary", "gemini-2.5-flash", False)
    assert r.source.ai_call_id == r.call_id and r.attempts == 1
    row = gw.repo.get("ai_calls", {"id": r.call_id})
    assert row["request_id"] == r.request_id and row["status"] == "success" and row["key_slot"] == 1
    assert row["valid"] is True and row["output"] == VALID_OUTPUT and row["fallback_from"] is None
    fake = gw.provider("gemini")
    assert (
        len(fake.requests) == 1 and fake.requests[0].timeout_s == 20 and fake.requests[0].temperature == 0.2
    )
    assert fake.calls == [("gemini-2.5-flash", 1)]


async def test_rate_limit_rotates_to_next_key_and_cools_the_first(gw):
    gw.provider("gemini").script = [ProviderError("rate_limited"), VALID_OUTPUT]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "gemini_primary" and r.attempts == 2
    assert [c[1] for c in gw.provider("gemini").calls] == [1, 2]
    assert gw.keyring.in_cooldown(1, "gemini-2.5-flash")
    rows = gw.repo.query("select id, status, fallback_from from ai_calls order by at", ())
    assert [x["status"] for x in rows] == ["rate_limited", "success"]
    assert rows[1]["fallback_from"] == rows[0]["id"]


async def test_bounds_and_check_rejections_count_as_invalid_output(gw):
    gw.provider("gemini").script = [
        {"multiplier": 3.0, "narrative": "x"},
        {"multiplier": 1.0, "narrative": "override"},
    ]
    gw.provider("ollama").script = [VALID_OUTPUT]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "gemma_local"
    rows = gw.repo.query("select tier, status, valid from ai_calls order by at", ())
    assert [(x["tier"], x["status"], x["valid"]) for x in rows] == [
        ("gemini_primary", "invalid_output", False),
        ("gemini_secondary", "invalid_output", False),
        ("gemma_local", "success", True),
    ]


async def test_exhausted_fake_script_is_unavailable_and_rules_never_fail(gw):
    r = await gw.call(ROLE, INPUT, Priority.BACKGROUND)  # no scripts at all
    assert r.source.tier == "rules" and r.output.narrative == "Rules: zone KSL-B3"
    assert r.source.model is None and r.source.cached is False
    rows = gw.repo.query("select tier, status, key_slot from ai_calls order by at", ())
    assert [(x["tier"], x["status"]) for x in rows] == [
        ("gemini_primary", "unavailable"),
        ("gemini_secondary", "unavailable"),
        ("gemma_local", "unavailable"),
        ("rules", "success"),
    ]


async def test_rules_answers_are_not_cached(gw):
    await gw.call(ROLE, INPUT, Priority.FLAGGED)  # rules (nothing scripted)
    gw.provider("gemini").script = [VALID_OUTPUT]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "gemini_primary" and r.source.cached is False


async def test_skipped_tiers_logged_and_ai_call_event_payload(gw):
    sub = gw.bus.subscribe()
    for s in (1, 2, 3):
        gw.keyring.cooldown(s, "gemini-2.5-flash")
        gw.keyring.cooldown(s, "gemini-3.1-flash-lite")
    gw.provider("ollama").script = [VALID_OUTPUT]
    r = await gw.call(ROLE, INPUT, Priority.OPERATOR)
    assert r.source.tier == "gemma_local"
    events = []
    while len(events) < 3:
        events.append(await asyncio.wait_for(sub.__anext__(), 1))
    assert [e.type for e in events] == ["ai.call"] * 3
    assert [e.data["status"] for e in events] == ["skipped", "skipped", "success"]
    last = events[-1].data
    for k in ("call_id", "role", "tier", "status", "cached", "fallback_from"):
        assert k in last
    assert last["role"] == "risk_interpreter" and last["tier"] == "gemma_local" and last["cached"] is False
    assert last["fallback_from"] == events[1].data["call_id"] and last["call_id"] == r.call_id


async def test_token_bucket_exhaustion_skips_key_without_cooldown(gw):
    m = "gemini-2.5-flash"
    for _ in range(5):
        assert gw.bucket(1, m).try_take()
    gw.provider("gemini").script = [VALID_OUTPUT]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "gemini_primary" and gw.provider("gemini").calls == [(m, 2)]
    assert not gw.keyring.in_cooldown(1, m)


async def test_success_resets_cooldown_strikes(gw):
    ring, m = gw.keyring, "gemini-2.5-flash"
    ring.cooldown(1, m)
    gw.clock.advance(60)
    ring.reset(1, m)
    ring.cooldown(1, m)  # first strike again -> 60 s, not 120 s
    gw.clock.advance(60)
    assert not ring.in_cooldown(1, m)


async def test_cooldown_caps_at_600s(gw):
    ring, m = gw.keyring, "gemini-2.5-flash"
    for _ in range(6):  # 60, 120, 240, 480, 600, 600
        ring.cooldown(1, m)
    gw.clock.advance(599)
    assert ring.in_cooldown(1, m)
    gw.clock.advance(1)
    assert not ring.in_cooldown(1, m)


def test_cache_key_is_sha256_of_canonical_json():
    import hashlib

    a = cache_key("r", "1", "p1", "m", {"b": 1, "a": [1, 2]}, ["h1"])
    b = cache_key("r", "1", "p1", "m", {"a": [1, 2], "b": 1}, ["h1"])
    assert a == b and len(a) == 64
    doc = {
        "image_hashes": ["h1"],
        "inputs": {"a": [1, 2], "b": 1},
        "model": "m",
        "prompt_version": "p1",
        "role": "r",
        "schema_version": "1",
    }
    assert a == hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert cache_key("r", "1", "p1", "other", {"a": [1, 2], "b": 1}, ["h1"]) != a


async def test_status_shape(gw):
    gw.provider("gemini").script = [VALID_OUTPUT]
    await gw.call(ROLE, INPUT, Priority.FLAGGED)
    gw.keyring.cooldown(2, "gemini-3.1-flash-lite")
    st = gw.status()
    ri = st.roles["risk_interpreter"]
    assert (ri.last_tier, ri.last_status, ri.degraded) == ("gemini_primary", "success", False)
    assert st.roles["vision_analyst"].last_tier is None
    keys = {(k.slot, k.model): k for k in st.keys}
    assert keys[(2, "gemini-3.1-flash-lite")].state == "cooldown"
    assert keys[(2, "gemini-3.1-flash-lite")].cooldown_until is not None
    assert keys[(1, "gemini-2.5-flash")].tokens == 4
    assert st.daily == {"gemini-2.5-flash": 1}
    assert st.ollama.model == "gemma4:e4b"


async def test_status_degraded_when_answered_by_rules(gw):
    await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert gw.status().roles["risk_interpreter"].degraded is True


async def test_priority_gate_serves_operator_before_background():
    gate = PriorityGate(1)
    order: list[str] = []
    await gate.acquire(Priority.FLAGGED)

    async def worker(name: str, p: Priority) -> None:
        await gate.acquire(p)
        order.append(name)
        gate.release()

    bg = asyncio.create_task(worker("background", Priority.BACKGROUND))
    await asyncio.sleep(0)
    op = asyncio.create_task(worker("operator", Priority.OPERATOR))
    await asyncio.sleep(0)
    gate.release()
    await asyncio.gather(bg, op)
    assert order == ["operator", "background"]


async def test_priority_gate_keeps_a_slot_free_from_background():
    gate = PriorityGate(2)
    await gate.acquire(Priority.BACKGROUND)
    blocked = asyncio.create_task(gate.acquire(Priority.BACKGROUND))
    await asyncio.sleep(0)
    assert not blocked.done()  # background may not take the last slot
    await asyncio.wait_for(gate.acquire(Priority.OPERATOR), 1)  # operator still gets in
    blocked.cancel()


# ---- fix round 1 ------------------------------------------------------------------------------
async def test_key_error_tries_next_slot_and_cools_the_failing_key(gw):
    m = "gemini-2.5-flash"
    gw.provider("gemini").script = [ProviderError("error", "400 API key not valid"), VALID_OUTPUT]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "gemini_primary" and gw.provider("gemini").calls == [(m, 1), (m, 2)]
    assert gw.keyring.in_cooldown(1, m)


class _BlockingProvider:
    """Answers VALID_OUTPUT; a request whose text mentions ``hold`` waits for ``release`` first."""

    provider = "ollama"

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.holding = asyncio.Event()

    async def generate(self, model: str, req: ProviderRequest, key_slot: int | None) -> dict:
        if any(isinstance(p, str) and "hold" in p for p in req.parts):
            self.holding.set()
            await self.release.wait()
        return dict(VALID_OUTPUT)


async def test_background_on_local_tier_never_blocks_operator(gw):
    for s in (1, 2, 3):
        gw.keyring.cooldown(s, "gemini-2.5-flash")
        gw.keyring.cooldown(s, "gemini-3.1-flash-lite")
    local = _BlockingProvider()
    gw.providers["ollama"] = local
    bg = asyncio.create_task(gw.call(ROLE, {"zone": "hold", "stress": 0.1}, Priority.BACKGROUND))
    await asyncio.wait_for(local.holding.wait(), 2)  # background holds a Gemma slot
    r = await asyncio.wait_for(gw.call(ROLE, INPUT, Priority.OPERATOR), 2)
    assert r.source.tier == "gemma_local"
    local.release.set()
    assert (await bg).source.tier == "gemma_local"


async def test_failed_log_write_does_not_cost_the_rules_answer(gw, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(gw.repo, "insert", boom)
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "rules" and r.output.narrative == "Rules: zone KSL-B3"


# ---- final review fixes -----------------------------------------------------------------------
async def test_gemini_timeouts_drop_to_gemma_within_the_role_budget(gw):  # Review Focus 1, slow network
    gw.provider("gemini").script = [ProviderError("timeout")] * 6
    gw.provider("ollama").script = [VALID_OUTPUT]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "gemma_local" and r.elapsed_s <= 60
    # a timeout cools that key and moves to the next tier: one attempt per Gemini tier
    assert gw.provider("gemini").calls == [("gemini-2.5-flash", 1), ("gemini-3.1-flash-lite", 1)]
    assert gw.keyring.in_cooldown(1, "gemini-2.5-flash")
    assert gw.keyring.in_cooldown(1, "gemini-3.1-flash-lite")


async def test_vision_timeouts_leave_gemma_a_share_of_the_budget(gw):
    gw.provider("gemini").script = [ProviderError("timeout")] * 6
    gw.provider("ollama").script = [VALID_OUTPUT]
    img_role = _ImageRole()
    r = await gw.call(img_role, INPUT, Priority.FLAGGED)
    assert r.source.tier == "gemma_local" and r.elapsed_s <= 60
    local_timeout = gw.provider("ollama").requests[0].timeout_s
    assert local_timeout >= 15  # a usable share of the 60 s budget is left for the local model


class _ImageRole(_TestRole):
    def request(self, inp: dict[str, Any]) -> ProviderRequest:
        req = super().request(inp)
        req.parts = [*req.parts, b"\xff\xd8 jpeg"]
        return req


async def test_operator_call_skips_the_cache_read_but_still_writes(gw):
    gw.provider("gemini").script = [VALID_OUTPUT, {**VALID_OUTPUT, "narrative": "Fresh look."}]
    await gw.call(ROLE, INPUT, Priority.FLAGGED)
    r = await gw.call(ROLE, INPUT, Priority.OPERATOR)
    assert r.source.cached is False and r.output.narrative == "Fresh look."
    c = await gw.call(ROLE, INPUT, Priority.FLAGGED)  # the operator's answer is the newest cache entry
    assert c.source.cached is True and c.output.narrative == "Fresh look."


async def test_gemma_answers_are_not_served_from_the_cache(gw):
    gw.provider("ollama").script = [VALID_OUTPUT]  # Gemini unavailable -> Gemma answers
    assert (await gw.call(ROLE, INPUT, Priority.FLAGGED)).source.tier == "gemma_local"
    gw.provider("gemini").script = [VALID_OUTPUT]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "gemini_primary" and r.source.cached is False


async def test_request_scoped_error_moves_to_next_tier_without_cooling_keys(gw):
    m = "gemini-2.5-flash"
    gw.provider("gemini").script = [ProviderError("error", "HTTP 400 request payload size exceeds the limit")]
    gw.provider("ollama").script = [VALID_OUTPUT]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "gemma_local"
    assert [c for c in gw.provider("gemini").calls if c[0] == m] == [(m, 1)]  # no other key tried
    assert not gw.keyring.in_cooldown(1, m)


async def test_key_scoped_errors_cool_the_key(gw):
    m = "gemini-2.5-flash"
    gw.provider("gemini").script = [
        ProviderError("error", "HTTP 403 PERMISSION_DENIED"),
        ProviderError("error", "HTTP 401 UNAUTHENTICATED"),
        VALID_OUTPUT,
    ]
    r = await gw.call(ROLE, INPUT, Priority.FLAGGED)
    assert r.source.tier == "gemini_primary" and [c[1] for c in gw.provider("gemini").calls] == [1, 2, 3]
    assert gw.keyring.in_cooldown(1, m) and gw.keyring.in_cooldown(2, m)
