"""Opt-in cloud suite (addendum P5): RLS, ledger trigger, Realtime publication, private buckets, A8 table.

Run: ``uv run pytest supabase/cloud-tests -m cloud -q`` (needs the gitignored ``.env``).
"""

from __future__ import annotations

import os

import httpx
import psycopg
import pytest

pytestmark = pytest.mark.cloud

BUCKETS = {"captures", "futures", "evidence-packs", "sim-sessions"}
REALTIME = {
    "telemetry",
    "alerts",
    "zone_assessments",
    "tasks",
    "captures",
    "ledger_records",
    "system_heartbeats",
}


def as_role(conn, role):
    """Transaction context that runs as ``role`` and always rolls back."""

    class _Ctx:
        def __enter__(self):
            self.tx = conn.transaction(force_rollback=True)
            self.tx.__enter__()
            conn.execute(f"set local role {role}")
            return conn

        def __exit__(self, *exc):
            return self.tx.__exit__(*exc)

    return _Ctx()


def test_anon_can_read_but_not_write(conn, schema, anon_site):
    with as_role(conn, "anon") as c:
        assert [r[0] for r in c.execute(f"select id from {schema}.sites").fetchall()] == [anon_site]
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_role(conn, "anon") as c:
        c.execute(f"insert into {schema}.sites (id) values ('ZZZ')")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_role(conn, "anon") as c:
        c.execute(f"delete from {schema}.sites")


def test_device_keys_unreadable_by_anon(conn, schema):
    for role in ("anon", "authenticated"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), as_role(conn, role) as c:
            c.execute(f"select * from {schema}.device_keys")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_role(conn, "authenticated") as c:
        c.execute(f"select id from {schema}.sites")


def test_ledger_trigger_rejects_update_delete_and_truncate(conn, schema, scratch_ledger_row):
    for role in ("service_role", "postgres"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"), as_role(conn, role) as c:
            c.execute(
                f"update {schema}.ledger_records set label = 'x' where chain_index = %s",
                (scratch_ledger_row,),
            )
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"), as_role(conn, role) as c:
            c.execute(f"delete from {schema}.ledger_records where chain_index = %s", (scratch_ledger_row,))
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"), as_role(conn, "postgres") as c:
        c.execute(f"truncate {schema}.ledger_records")
    assert conn.execute(f"select count(*) from {schema}.ledger_records").fetchone()[0] == 1


def test_realtime_publication_and_private_buckets(conn, schema):
    tables = {r[0] for r in conn.execute(f"select tablename from {schema}.bcs_test_publication_tables()")}
    assert REALTIME <= tables
    assert "device_keys" not in tables
    rows = conn.execute("select id, public, file_size_limit from storage.buckets").fetchall()
    found = {r[0]: r for r in rows if r[0] in BUCKETS}
    assert set(found) == BUCKETS
    assert all(r[1] is False and r[2] == 20971520 for r in found.values())


def test_bcs_db_size_service_role_only(conn, schema):
    with as_role(conn, "service_role") as c:
        assert c.execute(f"select {schema}.bcs_db_size()").fetchone()[0] > 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_role(conn, "anon") as c:
        c.execute(f"select {schema}.bcs_db_size()")


def test_hosted_rest_anon_read_only_and_keys_hidden():
    """Read-only probes of the real public schema through PostgREST with the anon key."""
    url = os.environ["BCS_SUPABASE_URL"].rstrip("/") + "/rest/v1"
    h = {
        "apikey": os.environ["BCS_SUPABASE_ANON_KEY"],
        "Authorization": "Bearer " + os.environ["BCS_SUPABASE_ANON_KEY"],
    }
    assert httpx.get(f"{url}/sites?select=id", headers=h, timeout=20).status_code == 200
    assert httpx.get(f"{url}/device_keys?select=*", headers=h, timeout=20).status_code in (401, 403)
    r = httpx.post(
        f"{url}/sites", headers={**h, "Content-Type": "application/json"}, json={"id": "ZZZ"}, timeout=20
    )
    assert r.status_code in (401, 403)
