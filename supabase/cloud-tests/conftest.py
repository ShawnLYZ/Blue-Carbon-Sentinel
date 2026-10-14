"""Opt-in cloud suite fixtures (addendum P5). Local only, never CI.

The suite applies migrations 1 and 2 to a scratch schema ``bcs_test_<timestamp>`` in the hosted project
over a direct database connection (the PostgREST API only exposes ``public``), exercises roles with
``SET ROLE``, and drops the schema afterwards. Realtime and bucket checks (migration 3 is global, not
schema scoped) read the hosted state read-only. Secrets are read from the environment or the
gitignored ``.env``; nothing is printed.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def pytest_collection_modifyitems(config, items):
    expr = (config.getoption("markexpr") or "").strip()
    if "cloud" not in expr or expr.startswith("not "):
        return  # default run: cloud tests are deselected; do not touch the environment
    _load_env()
    if os.environ.get("BCS_SUPABASE_ANON_KEY") and os.environ.get("SUPABASE_DB_PASSWORD"):
        return
    skip = pytest.mark.skip(reason="BCS_SUPABASE_ANON_KEY / SUPABASE_DB_PASSWORD not set")
    for item in items:
        if "cloud" in item.keywords:
            item.add_marker(skip)


def _conninfo() -> dict:
    # supabase/.temp/pooler-url (written by `supabase link`) holds user, host and port, no password.
    u = urlparse((ROOT / "supabase" / ".temp" / "pooler-url").read_text().strip())
    return {
        "host": u.hostname,
        "port": u.port or 5432,
        "user": unquote(u.username or "postgres"),
        "dbname": (u.path or "/postgres").lstrip("/") or "postgres",
        "password": os.environ["SUPABASE_DB_PASSWORD"],
        "autocommit": True,
        "connect_timeout": 20,
    }


@pytest.fixture(scope="session")
def conn():
    import psycopg

    with psycopg.connect(**_conninfo()) as c:
        yield c


@pytest.fixture(scope="session")
def schema(conn):
    name = f"bcs_test_{time.strftime('%Y%m%d%H%M%S')}"
    conn.execute(f"create schema {name}")
    try:
        conn.execute(f"grant usage on schema {name} to anon, authenticated, service_role")
        conn.execute(
            f"alter default privileges in schema {name} grant all on tables to anon, authenticated, service_role"
        )
        for f in sorted(MIGRATIONS.glob("*.sql"))[:2]:  # migration 3 is global (publication, buckets)
            conn.execute(f.read_text(encoding="utf-8").replace("public.", f"{name}."))
        conn.execute(
            f"""create function {name}.bcs_test_publication_tables() returns table(tablename name)
            language sql security definer set search_path = ''
            as $$ select tablename from pg_publication_tables
                  where pubname = 'supabase_realtime' and schemaname = 'public' $$"""
        )
        yield name
    finally:
        conn.execute(f"drop schema if exists {name} cascade")


@pytest.fixture
def anon_site(conn, schema):
    sid = f"T{uuid.uuid4().hex[:5]}".upper()
    conn.execute(
        f"""insert into {schema}.sites (id, name, status, region, centre_lat, centre_lng, bearing_deg,
        rationale, updated_at) values (%s, 'Scratch', 'planned', 'x', 0, 0, 0, 'x', now())""",
        (sid,),
    )
    return sid


@pytest.fixture
def scratch_ledger_row(conn, schema):
    idx = int(time.time())
    conn.execute(
        f"""insert into {schema}.ledger_records (chain_index, record_id, type, created_at, site_id, zone_ids,
        period, quantity_tco2e, gross_tco2e, deductions, evidence, confidence, method_note, label, canonical,
        previous_hash, hash) values (%s, %s, 'projected', now(), 'KSL', '[]', '{{}}', 1.234, 1.234, '{{}}',
        '{{}}', '{{}}', 'n', 'l', '{{}}', %s, %s)""",
        (idx, f"BC-T-{idx}", "0" * 64, "f" * 64),
    )
    return idx
