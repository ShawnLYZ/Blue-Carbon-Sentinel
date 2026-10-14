"""M7 Task 3: a fresh machine hydrates its local store from the Cloud Store (addendum H6)."""

from __future__ import annotations

import asyncio

from bcs_gs.store.cloud import CloudError, FakeCloudTarget
from bcs_gs.store.hydrate import hydrate, select_all


async def test_hydration_restores_and_chain_verifies(cloud_with_history, tmp_path, start_gs_with):  # Review Focus 3
    gs = await start_gs_with(cloud=cloud_with_history, data_dir=tmp_path)  # empty local store
    assert (await gs.http.get("/api/v1/ledger/records")).json() and (await gs.http.post("/api/v1/ledger/verify")).json()["intact"]
    assert len((await gs.http.get("/api/v1/nodes")).json()) == 8 and (await gs.http.get("/api/v1/forecasts/latest")).status_code == 200


async def test_hydration_writes_no_outbox_echo_and_restores_telemetry_and_media(
    cloud_with_history, tmp_path, start_gs_with
):
    gs = await start_gs_with(cloud=cloud_with_history, data_dir=tmp_path)
    svc = gs.services
    assert await asyncio.to_thread(svc.repo.query, "SELECT 1 FROM telemetry LIMIT 1")
    hydrated_ids = {r["id"] for r in await asyncio.to_thread(svc.repo.query, "SELECT id FROM restoration_plans")}
    assert hydrated_ids
    # Nothing hydrated is echoed back. New rows only: the site row's refresh, the re-issued simulated node
    # identities (keys are never pulled from the cloud) and the station's heartbeat.
    queued = await asyncio.to_thread(svc.repo.query, "SELECT DISTINCT table_name FROM sync_outbox")
    assert {q["table_name"] for q in queued} <= {
        "sites", "device_keys", "device_history", "system_heartbeats",
    }
    media = await asyncio.to_thread(svc.repo.query, "SELECT key FROM media_objects WHERE bucket = 'captures'")
    assert media and all(svc.media.path("captures", m["key"]).is_file() for m in media)


async def test_hydrate_is_idempotent_and_reports(cloud_with_history, tmp_path, start_gs_with):
    gs = await start_gs_with(cloud=cloud_with_history, data_dir=tmp_path)
    svc = gs.services
    report = await asyncio.to_thread(hydrate, svc.repo, svc.media, cloud_with_history, svc.clock)
    assert report.tables["ledger_records"] == 0 and report.chain_intact is True  # nothing new the second time
    assert report.media == 0


async def test_hydration_skips_telemetry_older_than_24h(cloud_with_history, tmp_path, start_gs_with):
    rows = list(cloud_with_history.tables["telemetry"].values())
    old = {**rows[0], "id": "00000000-0000-7000-8000-00000000dead", "seq": 99999, "sampled_at": "2026-10-10T00:00:00.000Z"}
    cloud_with_history.upsert("telemetry", [old], ("id",))
    gs = await start_gs_with(cloud=cloud_with_history, data_dir=tmp_path)
    got = await asyncio.to_thread(gs.services.repo.query, "SELECT id FROM telemetry")
    assert old["id"] not in {g["id"] for g in got} and got


async def test_start_survives_unreachable_cloud(tmp_path, start_gs_with):
    gs = await start_gs_with(cloud=FakeCloudTarget(failing=True), data_dir=tmp_path)
    assert (await gs.http.get("/api/v1/system/status")).status_code == 200


def test_paging_reads_every_row():
    cloud = FakeCloudTarget()
    cloud.upsert("alerts", [{"id": f"a{i:04d}", "n": i} for i in range(2500)], ("id",))
    assert len(select_all(cloud, "alerts")) == 2500
    cloud.failing = True
    try:
        select_all(cloud, "alerts")
    except CloudError:
        pass
    else:
        raise AssertionError("a failing cloud must raise")


def test_paging_with_tied_sort_keys_loses_and_repeats_nothing():
    cloud = FakeCloudTarget()
    cloud.shuffle_ties = True  # the cloud may order rows tied on the sort key differently on each page
    cloud.upsert("telemetry", [{"id": f"t{i:04d}", "sampled_at": "2026-10-16T03:00:00.000Z"} for i in range(2500)], ("id",))
    ids = [r["id"] for r in select_all(cloud, "telemetry", order=["sampled_at"])]
    assert len(ids) == 2500 == len(set(ids))


class CountingCloud(FakeCloudTarget):
    """Shares another fake's data; counts selects and can fail from the Nth one on."""

    def __init__(self, base: FakeCloudTarget, fail_from: int | None = None) -> None:
        super().__init__()
        self.tables, self.objects = base.tables, base.objects
        self.selects, self.fail_from = 0, fail_from

    def select(self, *a, **kw):
        self.selects += 1
        if self.fail_from is not None and self.selects >= self.fail_from:
            raise CloudError("cloud went away mid-hydration")
        return super().select(*a, **kw)


async def _stop(gs) -> None:
    await gs.http.aclose()
    await asyncio.to_thread(gs.stop)


async def test_interrupted_hydration_is_completed_at_next_start(cloud_with_history, tmp_path, start_gs_with):
    flaky = CountingCloud(cloud_with_history, fail_from=10)
    gs = await start_gs_with(cloud=flaky, data_dir=tmp_path)
    assert (await gs.http.get("/api/v1/ledger/records")).json() == []  # stopped midway, history rows are partial
    assert await asyncio.to_thread(gs.services.repo.query, "SELECT 1 FROM commissioning_runs LIMIT 1") or flaky.selects >= 10
    await _stop(gs)
    healthy = CountingCloud(cloud_with_history)
    gs = await start_gs_with(cloud=healthy, data_dir=tmp_path)
    assert (await gs.http.get("/api/v1/ledger/records")).json() and healthy.selects > 0
    assert (await gs.http.post("/api/v1/ledger/verify")).json()["intact"]


async def test_complete_store_is_not_hydrated_again(cloud_with_history, tmp_path, start_gs_with):
    gs = await start_gs_with(cloud=CountingCloud(cloud_with_history), data_dir=tmp_path)
    assert (await gs.http.get("/api/v1/ledger/records")).json()
    await _stop(gs)
    again = CountingCloud(cloud_with_history)
    gs = await start_gs_with(cloud=again, data_dir=tmp_path)
    assert again.selects == 0 and (await gs.http.get("/api/v1/ledger/records")).json()


async def test_postgres_numbers_verify_but_a_differing_display_column_is_broken(
    cloud_with_history, tmp_path, start_gs_with
):
    rows = list(cloud_with_history.tables["ledger_records"].values())
    for r in rows:  # as Postgres numeric(14,3) comes back: a JSON number
        r["quantity_tco2e"], r["gross_tco2e"] = float(r["quantity_tco2e"]), float(r["gross_tco2e"])
    gs = await start_gs_with(cloud=cloud_with_history, data_dir=tmp_path)
    assert (await gs.http.post("/api/v1/ledger/verify")).json()["intact"]
    await _stop(gs)

    rows[0]["quantity_tco2e"] = rows[0]["quantity_tco2e"] + 7.5  # canonical untouched: the display column lies
    other = tmp_path / "second"
    other.mkdir()
    gs = await start_gs_with(cloud=cloud_with_history, data_dir=other)
    v = (await gs.http.post("/api/v1/ledger/verify")).json()
    assert v["intact"] is False and v["first_broken_index"] == rows[0]["chain_index"]


async def _settle_outbox(svc) -> None:
    """Drains on the Ground Station's loop until the outbox is empty (every row sent or dead-lettered)."""
    for _ in range(10):
        fut = asyncio.run_coroutine_threadsafe(svc.sync.drain_once(), svc.tasking.loop)
        await asyncio.wrap_future(fut)
        if svc.sync.status().queue == 0:
            return
    raise AssertionError("the outbox did not drain")


async def test_fresh_station_seeds_nothing_over_hydrated_rows(cloud_with_history, tmp_path, start_gs_with):
    """Final review I4: startup seeding (default calibration, CAM-01) runs after hydration, so it finds the
    hydrated rows and pushes nothing; the cloud (one active calibration, like Postgres) rejects nothing."""
    cloud = cloud_with_history
    active_before = [r for r in cloud.tables["calibrations"].values() if r["active"]]
    camera_before = dict(cloud.tables["devices"][("CAM-01",)])
    assert len(active_before) == 1
    calls_before = len(cloud.calls)
    gs = await start_gs_with(cloud=cloud, data_dir=tmp_path)
    svc = gs.services
    await _settle_outbox(svc)
    assert svc.sync.status().dead_letter == 0
    pushed = {c.table for c in cloud.calls[calls_before:]}
    assert not pushed & {"calibrations", "devices"}, pushed
    assert [r for r in cloud.tables["calibrations"].values() if r["active"]] == active_before
    assert cloud.tables["devices"][("CAM-01",)] == camera_before
    local = await asyncio.to_thread(svc.repo.query, "SELECT id FROM calibrations WHERE active = 1")
    assert [r["id"] for r in local] == [active_before[0]["id"]]


def test_fake_cloud_rejects_a_second_active_calibration():
    cloud = FakeCloudTarget()
    cloud.upsert("calibrations", [{"id": "c1", "active": True}], ("id",))
    try:
        cloud.upsert("calibrations", [{"id": "c2", "active": True}], ("id",))
    except CloudError as exc:
        assert exc.permanent
    else:
        raise AssertionError("a second active calibration must be rejected (calibrations_one_active)")
    assert [k for k, r in cloud.tables["calibrations"].items() if r["active"]] == [("c1",)]
    # deactivating the old one first, in the same batch, is what a calibration swap sends: accepted
    cloud.upsert("calibrations", [{"id": "c1", "active": False}, {"id": "c2", "active": True}], ("id",))
    assert [k for k, r in cloud.tables["calibrations"].items() if r["active"]] == [("c2",)]


def _root_conftest():
    """The repository-wide conftest (its ``_run_broker`` starts a real Mosquitto)."""
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "conftest.py"
    spec = importlib.util.spec_from_file_location("bcs_root_conftest", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, mod)  # its dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


async def test_hydrated_nodes_get_identities_and_come_online(cloud_with_history, tmp_path, start_gs_with):
    """Final review I5: a fresh laptop (empty store, fresh broker) hydrates 8 simulated nodes without keys
    (keys are never pulled from the cloud). The Ground Station re-issues their identities at start, and
    the simulator brings them online with no manual step."""
    import secrets
    import time

    from bcs_gs.nodes.broker_admin import BrokerAdmin
    from bcs_sim.config import load_sim_config
    from bcs_sim.gs_client import GsClient
    from bcs_sim.runtime import Runtime

    (tmp_path / "broker2").mkdir()
    brokers = _root_conftest()._run_broker(tmp_path / "broker2", secrets.token_urlsafe(24))
    broker = next(brokers)
    rt = client = None
    try:
        (tmp_path / "fresh").mkdir()
        gs = await start_gs_with(
            cloud=cloud_with_history, data_dir=tmp_path / "fresh", broker_port=broker.port,
            broker_admin_user=broker.admin_user, broker_admin_password=broker.admin_password,
        )  # fmt: skip
        svc = gs.services
        nodes = [n for n in await asyncio.to_thread(svc.nodes.nodes) if n.source == "simulated"]
        assert len(nodes) == 8
        ids = {n.id for n in nodes}
        admin = BrokerAdmin("127.0.0.1", broker.port, broker.admin_user, broker.admin_password)
        deadline = time.monotonic() + 30
        while True:  # identities are re-issued by a startup task, before any simulator asks
            rows = await asyncio.to_thread(svc.repo.query, "SELECT device_id FROM device_keys")
            keyed = {r["device_id"] for r in rows}
            accounts = set(await asyncio.to_thread(admin.list_clients))
            if ids <= keyed and ids <= accounts:
                break
            assert time.monotonic() < deadline, f"keys {sorted(keyed)}, broker accounts {sorted(accounts)}"
            await asyncio.sleep(0.1)

        client = GsClient(gs.url, svc.settings.sim_shared_token.get_secret_value())
        rt = Runtime(
            load_sim_config(), client, gs.clock, seed=42, broker_host="127.0.0.1", broker_port=broker.port,
            watch_registry=False,
        )  # fmt: skip
        await asyncio.to_thread(rt.start)
        rt.run_background()
        deadline = time.monotonic() + 30
        while True:
            online = {n.id for n in await asyncio.to_thread(svc.nodes.nodes) if n.status == "online"}
            if ids <= online:
                break
            assert time.monotonic() < deadline, f"online: {sorted(online)}"
            await asyncio.sleep(0.1)
    finally:
        if rt is not None and rt.started:
            await asyncio.to_thread(rt.stop)
        if client is not None:
            client.close()
        brokers.close()


async def test_evidence_captures_come_from_the_canonical_content(cloud_with_history, tmp_path, start_gs_with):
    """Final review M9: the captures a ledger record's evidence references are read from its hashed canonical
    content, not the display ``evidence`` column (M6 ruling: read canonical)."""
    import json

    cloud = cloud_with_history
    rec = next(iter(cloud.tables["ledger_records"].values()))
    canonical_ids = {c["id"] for c in json.loads(rec["canonical"])["evidence"]["captures"]}
    assert canonical_ids
    decoy = {**next(iter(cloud.tables["captures"].values())), "id": "00000000-0000-7000-8000-0000000dec0y"}
    decoy["is_baseline"] = False
    cloud.upsert("captures", [decoy], ("id",))
    rec["evidence"] = {"captures": [{"id": decoy["id"]}]}  # the display column lies; the canonical does not
    gs = await start_gs_with(cloud=cloud, data_dir=tmp_path)
    got = {r["id"] for r in await asyncio.to_thread(gs.services.repo.query, "SELECT id FROM captures")}
    assert decoy["id"] not in got
    assert canonical_ids <= got


async def test_a_bad_media_key_is_skipped_not_fatal(cloud_with_history, tmp_path, start_gs_with):
    """Final review M11: a cloud media key the local store refuses (``media.path`` raises ValueError) is
    counted as skipped and logged; it must not abort hydration (which would then repeat at every start)."""
    cloud = cloud_with_history
    cap = next(c for c in cloud.tables["captures"].values() if c.get("is_baseline"))
    cap["media"] = {**(cap.get("media") or {}), "evil": "../../escape.png"}
    gs = await start_gs_with(cloud=cloud, data_dir=tmp_path)
    svc = gs.services
    assert (await gs.http.get("/api/v1/ledger/records")).json()  # the rest of the store was hydrated
    marker = await asyncio.to_thread(svc.repo.get, "settings", {"key": "hydration"})
    assert marker is not None and marker["value"]["state"] == "complete"
    report = await asyncio.to_thread(hydrate, svc.repo, svc.media, cloud, svc.clock)
    assert report.media_skipped >= 1
