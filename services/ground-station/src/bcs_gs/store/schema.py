"""Schema of the 25 synced tables (addendum H2), local tables (H3) and migrations.

Column order within each table follows H2 exactly; the Postgres migrations (Task 7) must match it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from bcs_gs.store.migration_v1 import V1_SQL

ColType = Literal["text", "int", "real", "numeric", "bool", "json", "timestamp"]

# Addendum H1 type map (SQLite side).
_SQL_TYPE: dict[str, str] = {
    "text": "TEXT",
    "int": "INTEGER",
    "real": "REAL",
    "numeric": "TEXT",
    "bool": "INTEGER",
    "json": "TEXT",
    "timestamp": "TEXT",
}

_TYPE_CODE: dict[str, ColType] = {
    "t": "text",
    "i": "int",
    "r": "real",
    "n": "numeric",
    "b": "bool",
    "j": "json",
    "ts": "timestamp",
}


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: dict[str, ColType]
    pk: tuple[str, ...]
    sync_op: Literal["upsert", "insert_ignore"] = "upsert"
    nullable: frozenset[str] = frozenset()
    foreign_keys: tuple[tuple[str, str, str], ...] = ()  # (column, ref_table, ref_column)
    uniques: tuple[tuple[str, ...], ...] = ()
    indexes: tuple[str, ...] = ()  # full CREATE INDEX statements

    def ddl(self) -> list[str]:
        parts: list[str] = []
        for col, typ in self.columns.items():
            sql = f'"{col}" {_SQL_TYPE[typ]}'
            if col not in self.nullable and col not in self.pk:
                sql += " NOT NULL"
            if len(self.pk) == 1 and col == self.pk[0]:
                sql += " PRIMARY KEY"
            parts.append(sql)
        if len(self.pk) > 1:
            parts.append("PRIMARY KEY (" + ", ".join(f'"{c}"' for c in self.pk) + ")")
        for cols in self.uniques:
            parts.append("UNIQUE (" + ", ".join(f'"{c}"' for c in cols) + ")")
        for col, ref_t, ref_c in self.foreign_keys:
            parts.append(f'FOREIGN KEY ("{col}") REFERENCES "{ref_t}" ("{ref_c}")')
        stmts = [f'CREATE TABLE "{self.name}" (\n  ' + ",\n  ".join(parts) + "\n)"]
        stmts.extend(self.indexes)
        return stmts


def _cols(spec: str) -> tuple[dict[str, ColType], frozenset[str]]:
    """Parse ``"a,b:t c:r?"`` into (columns in order, nullable names).

    A comma joins several names sharing a type; a trailing ``?`` marks them nullable.
    """
    cols: dict[str, ColType] = {}
    nullable: set[str] = set()
    for tok in spec.split():
        names, code = tok.split(":")
        null = code.endswith("?")
        code = code.rstrip("?")
        for n in names.split(","):
            cols[n] = _TYPE_CODE[code]
            if null:
                nullable.add(n)
    return cols, frozenset(nullable)


def _table(
    name: str,
    spec: str,
    pk: str,
    *,
    sync_op: Literal["upsert", "insert_ignore"] = "upsert",
    fks: tuple[tuple[str, str, str], ...] = (),
    uniques: tuple[tuple[str, ...], ...] = (),
    indexes: tuple[str, ...] = (),
) -> TableSpec:
    cols, nullable = _cols(spec)
    return TableSpec(
        name=name,
        columns=cols,
        pk=tuple(pk.split(",")),
        sync_op=sync_op,
        nullable=nullable,
        foreign_keys=fks,
        uniques=uniques,
        indexes=indexes,
    )


_TABLES: list[TableSpec] = [
    _table(
        "sites",
        "id:t name:t status:t region:t centre_lat,centre_lng:r anchor_nw_lat,anchor_nw_lng:r? "
        "bearing_deg:r size_m:r? scale_label:t? rationale:t updated_at:ts",
        "id",
    ),
    _table(
        "zones",
        "id:t site_id:t label:t coordinate_id:t col,row:i bounds:j bounds_site_m:j "
        "centre_lat,centre_lng:r area_ha:r",
        "id",
        uniques=(("coordinate_id",),),
    ),
    _table(
        "calibrations",
        "id:t created_at:ts mode:t frame_w,frame_h:i corners_px:j? north_edge:i? homography:j active:b",
        "id",
        indexes=(
            'CREATE UNIQUE INDEX "calibrations_one_active" ON "calibrations" ("active") WHERE "active" = 1',
        ),
    ),
    _table(
        "devices",
        "id:t kind:t node_type:t? source:t site_id:t e_m,s_m,lat,lng,u_px,v_px:r? zone_id:t? "
        "status:t mode:t? interval_s:i? fw_version,boot_id:t? installed_at,decommissioned_at,last_seen_at:ts? "
        "commissioning_run_id:t? updated_at:ts",
        "id",
    ),
    _table(
        "device_keys",
        "device_id:t key_hash:t created_at:ts rotations:i",
        "device_id",
        fks=(("device_id", "devices", "id"),),
    ),
    _table(
        "device_history",
        "id:t device_id:t at:ts change:t details:j",
        "id",
        fks=(("device_id", "devices", "id"),),
    ),
    _table(
        "commissioning_runs",
        "id:t created_at:ts capture_id:t? method:t confidence:t reasons:j positions:j coverage:j seed:i",
        "id",
    ),
    _table(
        "telemetry",
        "id:t node_id,boot_id:t seq:i sampled_at,received_at:ts mode:t readings,health,flags:j "
        "source:t replay,late:b",
        "id",
        fks=(("node_id", "devices", "id"),),
        uniques=(("node_id", "boot_id", "seq"),),
        indexes=('CREATE INDEX "telemetry_node_sampled" ON "telemetry" ("node_id", "sampled_at" DESC)',),
    ),
    _table(
        "node_events",
        "id:t node_id:t at:ts origin:t kind:t parameter:t? value,score:r? details:j boot_id:t? seq:i?",
        "id",
        fks=(("node_id", "devices", "id"),),
        indexes=(
            'CREATE INDEX "node_events_node_at" ON "node_events" ("node_id", "at" DESC)',
            (
                'CREATE UNIQUE INDEX "node_events_node_seq" ON "node_events" ("node_id", "boot_id", "seq") '
                "WHERE \"origin\" = 'node'"
            ),
        ),
    ),
    _table(
        "tasks",
        "id:t created_at,updated_at,expires_at:ts trigger:t zone_id:t? node_ids:j mode:t duration_s:i "
        "status:t reason:t cancelled_by:t? timeline:j",
        "id",
    ),
    _table(
        "commands",
        "id:t task_id:t? node_id,type:t params:j issued_at:ts expires_at:ts? ack_status:t ack_at:ts? retries:i",
        "id",
        fks=(("task_id", "tasks", "id"),),
    ),
    _table(
        "captures",
        "id:t taken_at:ts trigger:t imagery_source:t bands:j calibration_id:t frame_seq:i media:j "
        "media_state:t quality:j evidence_grade,is_baseline,flagged:b change_score:r? retention_reason:t?",
        "id",
        indexes=('CREATE INDEX "captures_taken_at" ON "captures" ("taken_at" DESC)',),
    ),
    _table(
        "zone_metrics",
        "capture_id,zone_id:t canopy_pct,water_pct,mud_pct,other_pct:r vari_mean,vari_p10,vari_p90:r? "
        "canopy_loss_pp,vari_drop:r? dieback_pct,new_growth_pct:r discolouration:r? flags:j",
        "capture_id,zone_id",
        fks=(("capture_id", "captures", "id"), ("zone_id", "zones", "id")),
        indexes=('CREATE INDEX "zone_metrics_zone" ON "zone_metrics" ("zone_id")',),
    ),
    _table(
        "tree_points",
        "id:t capture_id:t created_at:ts points:j tier:t model:t? ai_call_id:t?",
        "id",
    ),
    _table(
        "zone_assessments",
        "id:t zone_id:t at:ts capture_id:t? stressors:j multipliers,weights:j risk_score:r risk_class:t "
        "confidence:j early_warning:b narrative:t root_causes,actions:j tier:t model:t? cached:b ai_call_id:t? observations:j?",
        "id",
        indexes=('CREATE INDEX "zone_assessments_zone_at" ON "zone_assessments" ("zone_id", "at" DESC)',),
    ),
    _table(
        "ai_calls",
        "id:t request_id:t at:ts role,tier,provider:t model:t? key_slot:i? "
        "prompt_version,schema_version,input_hash,cache_key:t inputs,image_refs:j output:j? valid:b? "
        "latency_ms:i? status:t error:t? fallback_from:t? cache_hit:b",
        "id",
        indexes=(
            'CREATE INDEX "ai_calls_at" ON "ai_calls" ("at" DESC)',
            'CREATE INDEX "ai_calls_cache_key" ON "ai_calls" ("cache_key")',
        ),
    ),
    _table(
        "history_series",
        "id:t generation_id:t site_id,zone_id:t year:i metrics:j ai_call_id:t? label:t created_at:ts",
        "id",
        uniques=(("generation_id", "zone_id", "year"),),
    ),
    _table(
        "restoration_plans",
        "id:t plan_id:t version:i created_at:ts source:t status:t items:j applied_at:ts? "
        "capture_at_application_id,forecast_id,ai_call_id:t?",
        "id",
        uniques=(("plan_id", "version"),),
    ),
    _table(
        "forecasts",
        "id:t created_at:ts status:t plan_version_id:t? base_capture_id:t input_hash:t "
        "parameters,parameter_sources,keyframes,summary,bands:j",
        "id",
    ),
    _table(
        "illustrations",
        "id:t forecast_id:t year:i scenario:t media_key:t? provider,model,instruction:t seed:i status:t "
        "cache_key:t error:t? created_at,updated_at:ts",
        "id",
    ),
    _table(
        "ledger_records",
        "chain_index:i record_id:t type:t created_at:ts site_id:t zone_ids,period:j "
        "quantity_tco2e,gross_tco2e:n deductions,evidence,confidence:j method_note,label:t "
        "projected_record_id:t? canonical:t previous_hash:t hash:t",
        "chain_index",
        sync_op="insert_ignore",
        uniques=(("record_id",), ("hash",)),
    ),
    _table(
        "evidence_packs",
        "id:t record_id:t media_key:t generated_at:ts chain_intact:b bytes:i",
        "id",
        sync_op="insert_ignore",
    ),
    _table(
        "alerts",
        "id:t at,last_seen_at:ts occurrences:i type,severity:t zone_id,node_id:t? message,dedupe_key:t "
        "details:j acknowledged_at:ts?",
        "id",
        indexes=('CREATE INDEX "alerts_at" ON "alerts" ("at" DESC)',),
    ),
    _table(
        "sim_sessions",
        "id:t created_at:ts name,kind:t seed:i? duration_s:r message_count:i media_key:t",
        "id",
    ),
    _table(
        "system_heartbeats",
        "component:t at:ts status:t details:j",
        "component",
    ),
]

SYNCED_TABLES: dict[str, TableSpec] = {t.name: t for t in _TABLES}

# H3 local-only tables (never synced, no outbox). Their DDL is written by hand below (CHECKs,
# AUTOINCREMENT); the specs here drive Repo encoding/decoding.
LOCAL_TABLES: dict[str, TableSpec] = {
    t.name: t
    for t in [
        _table("schema_migrations", "version:i applied_at:ts", "version"),
        _table(
            "sync_outbox",
            "seq:i table_name:t op:t pk:j payload:j enqueued_at:ts attempts:i last_error:t?",
            "seq",
        ),
        _table(
            "sync_dead_letter",
            "seq:i table_name:t op:t pk:j payload:j enqueued_at:ts attempts:i last_error:t? dead_at:ts",
            "seq",
        ),
        _table(
            "media_objects",
            "bucket:t key:t local_path:t content_type:t bytes:i protected:b state:t uploaded_at:ts? "
            "attempts:i last_error:t?",
            "bucket,key",
        ),
        _table("settings", "key:t value:j updated_at:ts", "key"),
    ]
}

# Rows the cloud permanently rejected, moved out of sync_outbox (migration 2). Same columns plus dead_at.
_DEAD_LETTER_DDL = (
    'CREATE TABLE "sync_dead_letter" (\n'
    '  "seq" INTEGER PRIMARY KEY,\n'
    '  "table_name" TEXT NOT NULL,\n'
    '  "op" TEXT NOT NULL,\n'
    '  "pk" TEXT NOT NULL,\n'
    '  "payload" TEXT NOT NULL,\n'
    '  "enqueued_at" TEXT NOT NULL,\n'
    '  "attempts" INTEGER NOT NULL DEFAULT 0,\n'
    '  "last_error" TEXT,\n'
    '  "dead_at" TEXT NOT NULL\n'
    ")"
)

_LOCAL_DDL: list[str] = [
    (
        'CREATE TABLE "sync_outbox" (\n'
        '  "seq" INTEGER PRIMARY KEY AUTOINCREMENT,\n'
        '  "table_name" TEXT NOT NULL,\n'
        "  \"op\" TEXT NOT NULL CHECK (\"op\" IN ('upsert', 'insert_ignore')),\n"
        '  "pk" TEXT NOT NULL,\n'
        '  "payload" TEXT NOT NULL,\n'
        '  "enqueued_at" TEXT NOT NULL,\n'
        '  "attempts" INTEGER NOT NULL DEFAULT 0,\n'
        '  "last_error" TEXT\n'
        ")"
    ),
    _DEAD_LETTER_DDL,
    (
        'CREATE TABLE "media_objects" (\n'
        '  "bucket" TEXT NOT NULL,\n'
        '  "key" TEXT NOT NULL,\n'
        '  "local_path" TEXT NOT NULL,\n'
        '  "content_type" TEXT NOT NULL,\n'
        '  "bytes" INTEGER NOT NULL,\n'
        '  "protected" INTEGER NOT NULL DEFAULT 0,\n'
        '  "state" TEXT NOT NULL CHECK ("state" IN '
        "('pending', 'uploaded', 'pruned', 'failed', 'local_only')),\n"
        '  "uploaded_at" TEXT,\n'
        '  "attempts" INTEGER NOT NULL DEFAULT 0,\n'
        '  "last_error" TEXT,\n'
        '  PRIMARY KEY ("bucket", "key")\n'
        ")"
    ),
    'CREATE INDEX "media_objects_state" ON "media_objects" ("state")',
    (
        'CREATE TABLE "settings" (\n'
        '  "key" TEXT PRIMARY KEY,\n'
        '  "value" TEXT NOT NULL,\n'
        '  "updated_at" TEXT NOT NULL\n'
        ")"
    ),
]


def current_schema_sql() -> str:
    """DDL for the schema as SYNCED_TABLES + local tables describe it today (reference only).

    Not a migration: v1 is frozen in ``migration_v1``; changes after v1 are appended to MIGRATIONS.
    """
    stmts: list[str] = []
    for spec in SYNCED_TABLES.values():
        stmts.extend(spec.ddl())
    stmts.extend(_LOCAL_DDL)
    return ";\n".join(stmts)


# Applied in order; version = 1-based index. Statements within one migration are separated by ";\n".
# Entries are frozen once released: never edit one, append a new migration (e.g. ALTER TABLE ... ADD
# COLUMN) and update SYNCED_TABLES to match. test_store.py checks a from-scratch DB against SYNCED_TABLES.
# Migration 3: the zone's VisionAnalyst observations ({"items": [...], "source": chip|null}) on its assessment.
_ASSESSMENT_OBSERVATIONS_DDL = 'ALTER TABLE "zone_assessments" ADD COLUMN "observations" TEXT'

# Migration 4 (M6): ledger_records is append-only locally too (spec 23, H4). Each trigger is one statement
# (its body has no semicolon-newline, so the migration runner's split keeps it whole). RAISE(ABORT) is a constraint
# failure: sqlite3 raises IntegrityError "ledger_records is append-only".
LEDGER_TRIGGERS_DDL: tuple[str, ...] = tuple(
    f'CREATE TRIGGER "ledger_records_no_{op.lower()}" BEFORE {op} ON "ledger_records" '
    "BEGIN SELECT RAISE(ABORT, 'ledger_records is append-only'); END"
    for op in ("UPDATE", "DELETE")
)
LEDGER_TRIGGERS_DROP: tuple[str, ...] = tuple(
    f'DROP TRIGGER IF EXISTS "ledger_records_no_{op}"' for op in ("update", "delete")
)

MIGRATIONS: list[str] = [
    V1_SQL, _DEAD_LETTER_DDL, _ASSESSMENT_OBSERVATIONS_DDL, ";\n".join(LEDGER_TRIGGERS_DDL)
]  # fmt: skip

BOOTSTRAP_DDL = 'CREATE TABLE IF NOT EXISTS "schema_migrations" ("version" INTEGER PRIMARY KEY, "applied_at" TEXT NOT NULL)'
