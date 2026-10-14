"""M6 Task 5: the 8-section evidence pack PDF of a ledger record."""

import asyncio
import io

import pypdf
import pytest
from gs_ledger import create_projected

LABEL = "Demo record — not a certified carbon credit"
METHOD = "aligned with Verra VM0033 (Tidal Wetland and Seagrass Restoration) concepts — demo, not certified"


class _W:
    def __init__(self, w, rec):
        self._w, self.record_id, self.record_hash, self.record = w, rec["record_id"], rec["hash"], rec

    def __getattr__(self, name):
        return getattr(self._w, name)


@pytest.fixture
async def world_with_projected_record(world_applied_plan):
    return _W(world_applied_plan, await create_projected(world_applied_plan))


def _pages(content: bytes) -> list[str]:
    return [p.extract_text() for p in pypdf.PdfReader(io.BytesIO(content)).pages]


async def test_evidence_pack_contains_id_hash_and_simulated_label(world_with_projected_record):
    w = world_with_projected_record
    r = await w.http.get(f"/api/v1/ledger/records/{w.record_id}/evidence-pack")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    text = "\n".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(r.content)).pages)
    for needle in [
        w.record_id,
        w.record_hash,
        "SIMULATED",
        "Demo record — not a certified carbon credit",
        "aligned with Verra VM0033 (Tidal Wetland and Seagrass Restoration) concepts — demo, not certified",
    ]:
        assert needle in text
    assert (await w.rows("evidence_packs", record_id=w.record_id))[0]["chain_intact"] is True


async def test_every_page_footer_and_the_eight_sections(world_with_projected_record):
    w = world_with_projected_record
    r = await w.http.get(f"/api/v1/ledger/records/{w.record_id}/evidence-pack")
    pages = _pages(r.content)
    n = len(pages)
    for i, t in enumerate(pages, 1):
        assert f"{LABEL} · {w.record_id} · page {i}/{n}" in t
    text = "\n".join(pages)
    for title in (
        "1. Cover",
        "2. Chain proof",
        "3. Camera evidence",
        "4. Sensor evidence",
        "5. Forecast and plan summary",
        "6. AI provenance",
        "7. Methodology and constants",
        "8. Disclaimers",
    ):
        assert title in text
    assert "image not available for this capture" in text
    assert "tCO₂e" in text and "clamped at zero" in text


async def test_built_once_and_served_from_the_stored_file(world_with_projected_record):
    w = world_with_projected_record
    url = f"/api/v1/ledger/records/{w.record_id}/evidence-pack"
    a, b, c = await asyncio.gather(w.http.get(url), w.http.get(url), w.http.get(url))
    assert a.content == b.content == c.content
    rows = await w.rows("evidence_packs", record_id=w.record_id)
    assert (
        len(rows) == 1 and rows[0]["media_key"] == f"{w.record_id}.pdf" and rows[0]["bytes"] == len(a.content)
    )
    assert (w.gs.services.data_root / "var" / "media" / "evidence-packs" / f"{w.record_id}.pdf").is_file()
    assert (await w.http.get(url)).content == a.content
    assert len(await w.rows("evidence_packs")) == 1


async def test_unknown_record_is_404(world_with_projected_record):
    r = await world_with_projected_record.http.get("/api/v1/ledger/records/BC-2026-99999/evidence-pack")
    assert r.status_code == 404


async def test_broken_chain_is_stated_in_the_pack(world_with_projected_record):
    w = world_with_projected_record
    w.tamper(0)
    r = await w.http.get(f"/api/v1/ledger/records/{w.record_id}/evidence-pack")
    assert r.status_code == 200
    assert "BROKEN" in "\n".join(_pages(r.content))
    assert (await w.rows("evidence_packs", record_id=w.record_id))[0]["chain_intact"] is False


async def test_verified_record_pack(world_projected):  # final review: Verified packs carry AI provenance
    from gs_eligibility import seed_three_recovery_captures, verified_records

    w = world_projected
    await seed_three_recovery_captures(w, "KSL-B3", new_growth_pct=4.0)
    w.clock.advance(121)
    (rec,) = await verified_records(w)
    r = await w.http.get(f"/api/v1/ledger/records/{rec['record_id']}/evidence-pack")
    assert r.status_code == 200
    pages = _pages(r.content)
    text = "\n".join(pages)
    for needle in (rec["record_id"], rec["hash"], "SIMULATED", LABEL, METHOD, "Verified (demo)",
                   "Verification ratio", rec["content"]["verification_ratio"], rec["quantity_tco2e"]):  # fmt: skip
        assert needle in text, needle
    ai = next(p for p in pages if "6. AI provenance" in p)
    assert "No AI calls are cited" not in ai and "forecast_parameter_estimator" in ai
    for i, t in enumerate(pages, 1):
        assert f"{LABEL} · {rec['record_id']} · page {i}/{len(pages)}" in t


async def test_pack_of_a_broken_chain_raises_chain_broken_and_blocks(world_with_projected_record):
    w = world_with_projected_record
    w.tamper(0)
    assert w.ledger.issuance_blocked is False  # nothing has verified since the edit
    r = await w.http.get(f"/api/v1/ledger/records/{w.record_id}/evidence-pack")
    assert r.status_code == 200
    assert w.ledger.issuance_blocked is True
    assert any(a["type"] == "chain_broken" for a in (await w.http.get("/api/v1/alerts")).json())


async def test_zone_metrics_table_prints_each_capture_id_unbroken(world_projected):  # M6 follow-up: IDs wrapped
    from gs_eligibility import seed_three_recovery_captures, verified_records

    w = world_projected
    await seed_three_recovery_captures(w, "KSL-B3", new_growth_pct=4.0)
    w.clock.advance(121)
    (rec,) = await verified_records(w)
    r = await w.http.get(f"/api/v1/ledger/records/{rec['record_id']}/evidence-pack")
    camera = next(p for p in _pages(r.content) if "Zone metrics" in p)
    lines = camera.splitlines()
    ids = {c["id"] for c in rec["content"]["evidence"]["captures"]}
    assert len(ids) >= 3
    for cap_id in ids:  # one table row = one text line; a wrapped ID would be split from its zone cell
        assert any(cap_id in line and "KSL-B3" in line for line in lines), cap_id
