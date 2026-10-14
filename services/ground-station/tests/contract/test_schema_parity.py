"""Contract: Postgres migrations and the SQLite store expose identical tables and columns (H1, P4).

The Postgres side is the result of *all* migrations in order: ``create table`` statements plus any later
``alter table ... add column``. Other column-changing ``alter table`` forms (drop/rename/alter column
type) are not modelled and fail with a clear message, so the parser never silently drifts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from bcs_gs.store.schema import SYNCED_TABLES

MIGRATIONS = Path(__file__).resolve().parents[4] / "supabase" / "migrations"
CORE = MIGRATIONS / "20261007000001_core.sql"

# Addendum H1 type map: SQLite-side ColType -> the Postgres types it may be stored as.
H1_PG_TYPES: dict[str, set[str]] = {
    "text": {"uuid", "text", "char(64)"},
    "int": {"int2", "int4", "int8"},
    "real": {"float8"},
    "numeric": {"numeric"},
    "bool": {"bool"},
    "json": {"jsonb"},
    "timestamp": {"timestamptz"},
}
_PG_ALIASES = {
    "boolean": "bool",
    "smallint": "int2",
    "integer": "int4",
    "int": "int4",
    "bigint": "int8",
    "double precision": "float8",
    "timestamp with time zone": "timestamptz",
    "character(64)": "char(64)",
}
_TABLE_CONSTRAINTS = {"primary", "unique", "constraint", "check", "foreign", "exclude"}


@dataclass(frozen=True)
class PgColumn:
    name: str
    type: str  # normalised: numeric(14, 3) -> numeric, aliases folded
    not_null: bool


def _split_top_level(body: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _normalise_type(raw: str) -> str:
    t = re.sub(r"\s+", " ", raw.strip().lower())
    t = re.sub(r"\s*\(\s*", "(", t)
    t = re.sub(r"\s*\)", ")", t)
    t = _PG_ALIASES.get(t, t)
    if t.startswith("numeric"):
        return "numeric"
    return t


def _parse_column(item: str) -> PgColumn:
    m = re.match(r'"?(\w+)"?\s+(.*)$', item.strip(), re.DOTALL)
    assert m, f"cannot parse column definition: {item!r}"
    name, rest = m.group(1), m.group(2)
    tm = re.match(
        r"(double precision|timestamp with time zone|character\s*\(\s*\d+\s*\)|\w+(?:\s*\([^)]*\))?)",
        rest,
        re.IGNORECASE,
    )
    assert tm, f"cannot parse column type: {item!r}"
    lowered = rest.lower()
    return PgColumn(name, _normalise_type(tm.group(1)), "not null" in lowered or "primary key" in lowered)


def _sql(files: list[Path]) -> str:
    return re.sub(r"--[^\n]*", "", "\n".join(f.read_text(encoding="utf-8") for f in files))


_STMT = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?\"?(\w+)\"?\s*\("
    r"|alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?(?:public\.)?\"?(\w+)\"?\s+([^;]*);",
    re.IGNORECASE,
)


def parse_pg_schema(files: list[Path]) -> dict[str, list[PgColumn]]:
    """Return {table: [columns in order]} after applying every migration statement in order."""
    sql = _sql(files)
    tables: dict[str, list[PgColumn]] = {}
    for m in _STMT.finditer(sql):
        if m.group(1):  # create table
            depth, i = 1, m.end()
            while depth:
                depth += {"(": 1, ")": -1}.get(sql[i], 0)
                i += 1
            cols, pk_cols = [], set()
            for item in _split_top_level(sql[m.end() : i - 1]):
                if item.split()[0].strip('"').lower() in _TABLE_CONSTRAINTS:
                    pk = re.search(r"primary\s+key\s*\(([^)]*)\)", item, re.IGNORECASE)
                    if pk:  # table-level primary key columns are implicitly NOT NULL
                        pk_cols |= {c.strip().strip('"') for c in pk.group(1).split(",")}
                    continue
                cols.append(_parse_column(item))
            tables[m.group(1)] = [PgColumn(c.name, c.type, c.not_null or c.name in pk_cols) for c in cols]
            continue
        table, action = m.group(2), m.group(3).strip()
        for clause in _split_top_level(action):
            low = clause.lower()
            if re.match(r"add\s+(constraint|primary|unique|check|foreign|exclude)\b", low):
                continue
            add = re.match(r"add\s+(?:column\s+)?(?:if\s+not\s+exists\s+)?(.*)$", clause, re.IGNORECASE | re.DOTALL)
            if add:
                assert table in tables, f"alter table {table}: add column before create table"
                tables[table].append(_parse_column(add.group(1)))
            elif re.match(r"(drop|rename|alter)\b", low) and not re.match(r"(drop|alter|rename)\s+constraint\b", low):
                pytest.fail(
                    f"supabase migration changes columns of {table!r} with {clause!r}; "
                    "test_schema_parity only models CREATE TABLE and ADD COLUMN - extend the parser "
                    "and add the matching SQLite migration to bcs_gs.store.schema.MIGRATIONS"
                )
    return tables


def parse_create_tables(files: list[Path]) -> dict[str, list[str]]:
    """Return {table: [column names in order]} after all migrations."""
    return {t: [c.name for c in cols] for t, cols in parse_pg_schema(files).items()}


def test_postgres_migrations_match_sqlite_schema():
    pg = parse_create_tables(sorted(MIGRATIONS.glob("*.sql")))
    assert set(pg) == set(SYNCED_TABLES)
    for t, spec in SYNCED_TABLES.items():
        assert pg[t] == list(spec.columns), t


def test_column_types_follow_h1_type_map():
    """Every synced column's Postgres type is one H1 allows for its ColType, and nullability agrees."""
    core = parse_pg_schema([CORE])
    assert set(core) == set(SYNCED_TABLES), "the core migration must create all 25 synced tables"
    pg = parse_pg_schema(sorted(MIGRATIONS.glob("*.sql")))
    problems = []
    for t, spec in SYNCED_TABLES.items():
        by_name = {c.name: c for c in pg[t]}
        for col, coltype in spec.columns.items():
            pc = by_name[col]
            if pc.type not in H1_PG_TYPES[coltype]:
                problems.append(f"{t}.{col}: SQLite {coltype} vs Postgres {pc.type}")
            sqlite_not_null = col in spec.pk or col not in spec.nullable
            if pc.not_null != sqlite_not_null:
                problems.append(f"{t}.{col}: not null in SQLite={sqlite_not_null}, Postgres={pc.not_null}")
    assert not problems, "\n".join(problems)


def test_parser_applies_add_column_and_rejects_other_column_changes(tmp_path):
    a = tmp_path / "1.sql"
    a.write_text('create table public.t (\n  "id" uuid primary key,\n  "x" numeric(14, 3) not null\n);\n')
    b = tmp_path / "2.sql"
    b.write_text(
        "alter table public.t enable row level security;\n"
        'alter table public.t add column "y" timestamptz, add column if not exists "z" jsonb not null;\n'
        "alter table public.t add constraint t_x check (x > 0);\n"
    )
    cols = parse_pg_schema([a, b])["t"]
    assert [(c.name, c.type, c.not_null) for c in cols] == [
        ("id", "uuid", True),
        ("x", "numeric", True),
        ("y", "timestamptz", False),
        ("z", "jsonb", True),
    ]
    c = tmp_path / "3.sql"
    c.write_text('alter table public.t drop column "y";\n')
    with pytest.raises(pytest.fail.Exception, match="only models CREATE TABLE and ADD COLUMN"):
        parse_pg_schema([a, b, c])


def test_policies_and_trigger_present():
    sql = "\n".join(p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS.glob("*.sql"))).lower()
    assert "create trigger bcs_ledger_immutable" in sql
    assert sql.count("enable row level security") == 25
    policies = re.findall(r"create policy \w+ on public\.(\w+)", sql)
    assert "device_keys" not in policies
    assert len(policies) == 24
    for b in ["captures", "futures", "evidence-packs", "sim-sessions"]:
        assert f"'{b}'" in sql
    assert "bcs_db_size" in sql
    assert "foreign key" not in sql
