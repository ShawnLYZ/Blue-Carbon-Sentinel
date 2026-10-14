import sqlite3
from datetime import UTC, datetime

import pytest
from bcs_gs.core.clock import ManualClock
from bcs_gs.store.db import Database
from bcs_gs.store.media import MediaStore
from bcs_gs.store.outbox import Outbox
from bcs_gs.store.repo import Repo
from bcs_gs.store.schema import LOCAL_TABLES, MIGRATIONS, SYNCED_TABLES

T0 = "2026-10-16T03:04:05.123Z"
CAP_ID = "0199aaaa-0000-7000-8000-000000000001"

SITE_ROW = {
    "id": "KSL",
    "name": "Kuala Selangor",
    "status": "live",
    "region": "Selangor, Malaysia",
    "centre_lat": 3.3412,
    "centre_lng": 101.2437,
    "anchor_nw_lat": 3.3434,
    "anchor_nw_lng": 101.2415,
    "bearing_deg": 0.0,
    "size_m": 500.0,
    "scale_label": "1:500 (1 cm = 5 m)",
    "rationale": "Mangrove restoration site",
    "updated_at": T0,
}
LEDGER_ROW = {
    "chain_index": 0,
    "record_id": "BC-2026-00001",
    "type": "projected",
    "created_at": T0,
    "site_id": "KSL",
    "zone_ids": ["KSL-B3"],
    "period": {"from": "2026-10-16", "to": "2026-10-17"},
    "quantity_tco2e": "1.250",
    "gross_tco2e": "1.500",
    "deductions": [],
    "evidence": [],
    "confidence": {"overall": 0.8},
    "method_note": "note",
    "label": "Projected",
    "projected_record_id": None,
    "canonical": "{}",
    "previous_hash": "0" * 64,
    "hash": "a" * 64,
}
ZM_ROW = {
    "capture_id": CAP_ID,
    "zone_id": "KSL-B3",
    "canopy_pct": 40.0,
    "water_pct": 30.0,
    "mud_pct": 20.0,
    "other_pct": 10.0,
    "vari_mean": None,
    "vari_p10": None,
    "vari_p90": None,
    "canopy_loss_pp": None,
    "vari_drop": None,
    "dieback_pct": 0.0,
    "new_growth_pct": 0.0,
    "discolouration": None,
    "flags": [],
}
ALERT_ROW = {
    "id": "0199aaaa-0000-7000-8000-000000000002",
    "at": T0,
    "last_seen_at": T0,
    "occurrences": 1,
    "type": "node_offline",
    "severity": "warning",
    "zone_id": None,
    "node_id": None,
    "message": "m",
    "dedupe_key": "k",
    "details": {"a": [1, 2]},
    "acknowledged_at": None,
}


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "bcs.sqlite3", ManualClock(datetime(2026, 10, 16, 3, 4, 5, 123000, tzinfo=UTC)))
    d.migrate()
    yield d
    d.close()


def test_migrate_creates_all_25_synced_and_local_tables(db):
    names = {r["name"] for r in Repo(db).query("select name from sqlite_master where type='table'", ())}
    assert (
        set(SYNCED_TABLES) <= names
        and {"sync_outbox", "media_objects", "settings", "schema_migrations"} <= names
    )
    assert len(SYNCED_TABLES) == 25 and "device_keys" in SYNCED_TABLES


def test_migrate_is_idempotent_and_records_versions(db):
    db.migrate()
    rows = Repo(db).query("select version from schema_migrations", ())
    assert [r["version"] for r in rows] == list(range(1, len(MIGRATIONS) + 1))
    assert {"sync_outbox", "sync_dead_letter", "media_objects", "settings", "schema_migrations"} == set(
        LOCAL_TABLES
    )


V1_SHA256 = "72adea48254af66bc866b3415aa34196bb8b95743581a689d6f765c7da74570b"


def test_v1_migration_is_frozen():
    """v1 is a committed literal: editing it would diverge from DBs already at v1. Append a migration."""
    import hashlib

    from bcs_gs.store.migration_v1 import V1_SQL

    assert MIGRATIONS[0] is V1_SQL
    assert hashlib.sha256(V1_SQL.encode("utf-8")).hexdigest() == V1_SHA256, (
        "migration v1 changed; never edit it - append a new entry to schema.MIGRATIONS instead"
    )


def test_migrated_db_matches_synced_tables(db):
    """All migrations applied from scratch must produce exactly the columns SYNCED_TABLES specifies."""
    from bcs_gs.store.schema import _SQL_TYPE

    conn = db.read()
    try:
        for name, spec in {**SYNCED_TABLES, **{k: v for k, v in LOCAL_TABLES.items() if k != "schema_migrations"}}.items():
            info = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
            got = [(r["name"], r["type"], bool(r["notnull"]) or r["pk"] > 0, r["pk"] > 0) for r in info]
            want = [
                (c, _SQL_TYPE[t], c in spec.pk or c not in spec.nullable, c in spec.pk)
                for c, t in spec.columns.items()
            ]
            assert got == want, name
    finally:
        conn.close()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_real_rejected_before_write(db, bad):
    r = Repo(db)
    with pytest.raises(ValueError, match="non-finite"):
        r.upsert("sites", {**SITE_ROW, "centre_lat": bad})
    assert r.get("sites", {"id": "KSL"}) is None and Outbox(db).count() == 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_in_json_rejected_before_write(db, bad):
    r = Repo(db)
    with pytest.raises(ValueError, match="NaN or Infinity"):
        r.upsert("alerts", {**ALERT_ROW, "details": {"x": [1.0, bad]}})
    assert r.get("alerts", {"id": ALERT_ROW["id"]}) is None and Outbox(db).count() == 0


def test_pragmas(db):
    conn = db.read()
    try:
        assert conn.execute("pragma foreign_keys").fetchone()[0] == 1
        assert conn.execute("pragma journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_upsert_writes_row_and_outbox_atomically(db):
    r = Repo(db)
    r.upsert("sites", SITE_ROW)
    assert r.get("sites", {"id": "KSL"})["name"] == SITE_ROW["name"]
    item = Outbox(db).pending(10)[0]
    assert (item.table_name, item.op) == ("sites", "upsert")
    assert item.pk == {"id": "KSL"} and item.payload["name"] == SITE_ROW["name"]


def test_upsert_updates_existing_and_sync_false_skips_outbox(db):
    r = Repo(db)
    r.upsert("sites", SITE_ROW, sync=False)
    r.upsert("sites", {**SITE_ROW, "name": "Renamed"})
    assert r.get("sites", {"id": "KSL"})["name"] == "Renamed"
    assert r.get("sites", {"id": "KSL"})["region"] == SITE_ROW["region"]
    items = Outbox(db).pending(10)
    assert len(items) == 1 and items[0].payload["region"] == SITE_ROW["region"]


def test_ledger_rows_queue_as_insert_ignore(db):
    Repo(db).insert("ledger_records", LEDGER_ROW)
    assert Outbox(db).pending(10)[0].op == "insert_ignore"


@pytest.mark.parametrize("table", ["ledger_records", "evidence_packs"])
def test_upsert_refuses_insert_only_tables(db, table):  # M1 follow-up (ruling R6a)
    with pytest.raises(ValueError, match="insert-only"):
        Repo(db).upsert(table, LEDGER_ROW if table == "ledger_records" else {"id": "x"})
    assert Outbox(db).count() == 0


def test_ledger_rows_reject_update_and_delete(db):  # M6 Task 3: append-only triggers
    Repo(db).insert("ledger_records", LEDGER_ROW)
    with db.tx() as conn, pytest.raises(sqlite3.IntegrityError, match="ledger_records is append-only"):
        conn.execute("UPDATE ledger_records SET label = 'x'")
    with db.tx() as conn, pytest.raises(sqlite3.IntegrityError, match="ledger_records is append-only"):
        conn.execute("DELETE FROM ledger_records")
    assert Repo(db).get("ledger_records", {"chain_index": 0})["label"] == LEDGER_ROW["label"]


def test_failed_write_leaves_no_outbox_entry(db):
    with pytest.raises(sqlite3.IntegrityError):
        Repo(db).insert("zone_metrics", {**ZM_ROW, "capture_id": "missing"})  # foreign keys are on
    assert Outbox(db).count() == 0


def test_json_and_bool_round_trip(db):
    Repo(db).upsert("alerts", ALERT_ROW)
    got = Repo(db).get("alerts", {"id": ALERT_ROW["id"]})
    assert got["details"] == {"a": [1, 2]} and got["acknowledged_at"] is None


def test_outbox_ack_and_fail(db):
    r = Repo(db)
    r.upsert("alerts", ALERT_ROW)
    r.upsert("sites", SITE_ROW)
    o = Outbox(db)
    first, second = o.pending(10)
    o.fail([first.seq], "boom")
    again = o.pending(1)[0]
    assert again.seq == first.seq and again.attempts == 1 and again.last_error == "boom"
    o.ack([first.seq])
    assert [i.seq for i in o.pending(10)] == [second.seq] and o.count() == 1


def test_unknown_table_and_column_rejected(db):
    with pytest.raises(ValueError):
        Repo(db).upsert("nope", {"id": "x"})
    with pytest.raises(ValueError):
        Repo(db).upsert("sites", {"id": "KSL", "bogus": 1})


def test_media_put_local_only_until_promoted(tmp_path, db):
    m = MediaStore(tmp_path, db)
    key = "2026/10/16/x/image.jpg"
    p = m.put("captures", key, b"jpg", "image/jpeg", cloud=False)
    assert p.read_bytes() == b"jpg" and p == m.path("captures", key)
    assert Repo(db).get("media_objects", {"bucket": "captures", "key": key})["state"] == "local_only"
    m.promote("captures", [key])
    assert Repo(db).get("media_objects", {"bucket": "captures", "key": key})["state"] == "pending"
    assert Outbox(db).count() == 0


def test_media_put_cloud_is_pending_and_rejects_traversal(tmp_path, db):
    m = MediaStore(tmp_path, db)
    m.put("evidence-packs", "BC-2026-00001.pdf", b"x", "application/pdf", protected=True, cloud=True)
    row = Repo(db).get("media_objects", {"bucket": "evidence-packs", "key": "BC-2026-00001.pdf"})
    assert row["state"] == "pending" and row["protected"] is True
    with pytest.raises(ValueError):
        m.put("captures", "../evil", b"x", "text/plain", cloud=False)


@pytest.mark.parametrize(
    ("bucket", "key"),
    [
        ("captures", "C:/evil/x"),
        ("captures", "a/b:stream"),
        ("captures", "..\\x"),
        ("captures", "/abs"),
        ("captures", "a/../../x"),
        ("captures", "a//b"),
        ("captures", ""),
        ("unknown", "x.jpg"),
        ("..", "x.jpg"),
    ],
)
def test_media_rejects_unsafe_paths(tmp_path, db, bucket, key):
    m = MediaStore(tmp_path, db)
    with pytest.raises(ValueError):
        m.path(bucket, key)
    with pytest.raises(ValueError):
        m.put(bucket, key, b"x", "text/plain", cloud=False)
    assert not (tmp_path / "var" / "media").exists() or not any((tmp_path / "var" / "media").rglob("*.tmp"))
