"""Frozen SQLite migration v1 (generated once from SYNCED_TABLES + local tables on 2026-10-08).

Never edit this string: databases already migrated to v1 will not re-run it. Schema changes are new,
appended migrations in ``schema.MIGRATIONS`` (``ALTER TABLE ... ADD COLUMN`` etc.); the contract test
``test_store.py::test_v1_migration_is_frozen`` pins this text and
``test_migrated_db_matches_synced_tables`` checks the result of all migrations against SYNCED_TABLES.
"""

V1_STATEMENTS: tuple[str, ...] = (
    (
        'CREATE TABLE "sites" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "name" TEXT NOT NULL,\n'
        '  "status" TEXT NOT NULL,\n'
        '  "region" TEXT NOT NULL,\n'
        '  "centre_lat" REAL NOT NULL,\n'
        '  "centre_lng" REAL NOT NULL,\n'
        '  "anchor_nw_lat" REAL,\n'
        '  "anchor_nw_lng" REAL,\n'
        '  "bearing_deg" REAL NOT NULL,\n'
        '  "size_m" REAL,\n'
        '  "scale_label" TEXT,\n'
        '  "rationale" TEXT NOT NULL,\n'
        '  "updated_at" TEXT NOT NULL\n'
        ")"
    ),
    (
        'CREATE TABLE "zones" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "site_id" TEXT NOT NULL,\n'
        '  "label" TEXT NOT NULL,\n'
        '  "coordinate_id" TEXT NOT NULL,\n'
        '  "col" INTEGER NOT NULL,\n'
        '  "row" INTEGER NOT NULL,\n'
        '  "bounds" TEXT NOT NULL,\n'
        '  "bounds_site_m" TEXT NOT NULL,\n'
        '  "centre_lat" REAL NOT NULL,\n'
        '  "centre_lng" REAL NOT NULL,\n'
        '  "area_ha" REAL NOT NULL,\n'
        '  UNIQUE ("coordinate_id")\n'
        ")"
    ),
    (
        'CREATE TABLE "calibrations" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  "mode" TEXT NOT NULL,\n'
        '  "frame_w" INTEGER NOT NULL,\n'
        '  "frame_h" INTEGER NOT NULL,\n'
        '  "corners_px" TEXT,\n'
        '  "north_edge" INTEGER,\n'
        '  "homography" TEXT NOT NULL,\n'
        '  "active" INTEGER NOT NULL\n'
        ")"
    ),
    'CREATE UNIQUE INDEX "calibrations_one_active" ON "calibrations" ("active") WHERE "active" = 1',
    (
        'CREATE TABLE "devices" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "kind" TEXT NOT NULL,\n'
        '  "node_type" TEXT,\n'
        '  "source" TEXT NOT NULL,\n'
        '  "site_id" TEXT NOT NULL,\n'
        '  "e_m" REAL,\n'
        '  "s_m" REAL,\n'
        '  "lat" REAL,\n'
        '  "lng" REAL,\n'
        '  "u_px" REAL,\n'
        '  "v_px" REAL,\n'
        '  "zone_id" TEXT,\n'
        '  "status" TEXT NOT NULL,\n'
        '  "mode" TEXT,\n'
        '  "interval_s" INTEGER,\n'
        '  "fw_version" TEXT,\n'
        '  "boot_id" TEXT,\n'
        '  "installed_at" TEXT,\n'
        '  "decommissioned_at" TEXT,\n'
        '  "last_seen_at" TEXT,\n'
        '  "commissioning_run_id" TEXT,\n'
        '  "updated_at" TEXT NOT NULL\n'
        ")"
    ),
    (
        'CREATE TABLE "device_keys" (\n'
        '  "device_id" TEXT PRIMARY KEY,\n'
        '  "key_hash" TEXT NOT NULL,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  "rotations" INTEGER NOT NULL,\n'
        '  FOREIGN KEY ("device_id") REFERENCES "devices" ("id")\n'
        ")"
    ),
    (
        'CREATE TABLE "device_history" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "device_id" TEXT NOT NULL,\n'
        '  "at" TEXT NOT NULL,\n'
        '  "change" TEXT NOT NULL,\n'
        '  "details" TEXT NOT NULL,\n'
        '  FOREIGN KEY ("device_id") REFERENCES "devices" ("id")\n'
        ")"
    ),
    (
        'CREATE TABLE "commissioning_runs" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  "capture_id" TEXT,\n'
        '  "method" TEXT NOT NULL,\n'
        '  "confidence" TEXT NOT NULL,\n'
        '  "reasons" TEXT NOT NULL,\n'
        '  "positions" TEXT NOT NULL,\n'
        '  "coverage" TEXT NOT NULL,\n'
        '  "seed" INTEGER NOT NULL\n'
        ")"
    ),
    (
        'CREATE TABLE "telemetry" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "node_id" TEXT NOT NULL,\n'
        '  "boot_id" TEXT NOT NULL,\n'
        '  "seq" INTEGER NOT NULL,\n'
        '  "sampled_at" TEXT NOT NULL,\n'
        '  "received_at" TEXT NOT NULL,\n'
        '  "mode" TEXT NOT NULL,\n'
        '  "readings" TEXT NOT NULL,\n'
        '  "health" TEXT NOT NULL,\n'
        '  "flags" TEXT NOT NULL,\n'
        '  "source" TEXT NOT NULL,\n'
        '  "replay" INTEGER NOT NULL,\n'
        '  "late" INTEGER NOT NULL,\n'
        '  UNIQUE ("node_id", "boot_id", "seq"),\n'
        '  FOREIGN KEY ("node_id") REFERENCES "devices" ("id")\n'
        ")"
    ),
    'CREATE INDEX "telemetry_node_sampled" ON "telemetry" ("node_id", "sampled_at" DESC)',
    (
        'CREATE TABLE "node_events" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "node_id" TEXT NOT NULL,\n'
        '  "at" TEXT NOT NULL,\n'
        '  "origin" TEXT NOT NULL,\n'
        '  "kind" TEXT NOT NULL,\n'
        '  "parameter" TEXT,\n'
        '  "value" REAL,\n'
        '  "score" REAL,\n'
        '  "details" TEXT NOT NULL,\n'
        '  "boot_id" TEXT,\n'
        '  "seq" INTEGER,\n'
        '  FOREIGN KEY ("node_id") REFERENCES "devices" ("id")\n'
        ")"
    ),
    'CREATE INDEX "node_events_node_at" ON "node_events" ("node_id", "at" DESC)',
    'CREATE UNIQUE INDEX "node_events_node_seq" ON "node_events" ("node_id", "boot_id", "seq") WHERE "origin" = \'node\'',
    (
        'CREATE TABLE "tasks" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  "updated_at" TEXT NOT NULL,\n'
        '  "expires_at" TEXT NOT NULL,\n'
        '  "trigger" TEXT NOT NULL,\n'
        '  "zone_id" TEXT,\n'
        '  "node_ids" TEXT NOT NULL,\n'
        '  "mode" TEXT NOT NULL,\n'
        '  "duration_s" INTEGER NOT NULL,\n'
        '  "status" TEXT NOT NULL,\n'
        '  "reason" TEXT NOT NULL,\n'
        '  "cancelled_by" TEXT,\n'
        '  "timeline" TEXT NOT NULL\n'
        ")"
    ),
    (
        'CREATE TABLE "commands" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "task_id" TEXT,\n'
        '  "node_id" TEXT NOT NULL,\n'
        '  "type" TEXT NOT NULL,\n'
        '  "params" TEXT NOT NULL,\n'
        '  "issued_at" TEXT NOT NULL,\n'
        '  "expires_at" TEXT,\n'
        '  "ack_status" TEXT NOT NULL,\n'
        '  "ack_at" TEXT,\n'
        '  "retries" INTEGER NOT NULL,\n'
        '  FOREIGN KEY ("task_id") REFERENCES "tasks" ("id")\n'
        ")"
    ),
    (
        'CREATE TABLE "captures" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "taken_at" TEXT NOT NULL,\n'
        '  "trigger" TEXT NOT NULL,\n'
        '  "imagery_source" TEXT NOT NULL,\n'
        '  "bands" TEXT NOT NULL,\n'
        '  "calibration_id" TEXT NOT NULL,\n'
        '  "frame_seq" INTEGER NOT NULL,\n'
        '  "media" TEXT NOT NULL,\n'
        '  "media_state" TEXT NOT NULL,\n'
        '  "quality" TEXT NOT NULL,\n'
        '  "evidence_grade" INTEGER NOT NULL,\n'
        '  "is_baseline" INTEGER NOT NULL,\n'
        '  "flagged" INTEGER NOT NULL,\n'
        '  "change_score" REAL,\n'
        '  "retention_reason" TEXT\n'
        ")"
    ),
    'CREATE INDEX "captures_taken_at" ON "captures" ("taken_at" DESC)',
    (
        'CREATE TABLE "zone_metrics" (\n'
        '  "capture_id" TEXT,\n'
        '  "zone_id" TEXT,\n'
        '  "canopy_pct" REAL NOT NULL,\n'
        '  "water_pct" REAL NOT NULL,\n'
        '  "mud_pct" REAL NOT NULL,\n'
        '  "other_pct" REAL NOT NULL,\n'
        '  "vari_mean" REAL,\n'
        '  "vari_p10" REAL,\n'
        '  "vari_p90" REAL,\n'
        '  "canopy_loss_pp" REAL,\n'
        '  "vari_drop" REAL,\n'
        '  "dieback_pct" REAL NOT NULL,\n'
        '  "new_growth_pct" REAL NOT NULL,\n'
        '  "discolouration" REAL,\n'
        '  "flags" TEXT NOT NULL,\n'
        '  PRIMARY KEY ("capture_id", "zone_id"),\n'
        '  FOREIGN KEY ("capture_id") REFERENCES "captures" ("id"),\n'
        '  FOREIGN KEY ("zone_id") REFERENCES "zones" ("id")\n'
        ")"
    ),
    'CREATE INDEX "zone_metrics_zone" ON "zone_metrics" ("zone_id")',
    (
        'CREATE TABLE "tree_points" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "capture_id" TEXT NOT NULL,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  "points" TEXT NOT NULL,\n'
        '  "tier" TEXT NOT NULL,\n'
        '  "model" TEXT,\n'
        '  "ai_call_id" TEXT\n'
        ")"
    ),
    (
        'CREATE TABLE "zone_assessments" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "zone_id" TEXT NOT NULL,\n'
        '  "at" TEXT NOT NULL,\n'
        '  "capture_id" TEXT,\n'
        '  "stressors" TEXT NOT NULL,\n'
        '  "multipliers" TEXT NOT NULL,\n'
        '  "weights" TEXT NOT NULL,\n'
        '  "risk_score" REAL NOT NULL,\n'
        '  "risk_class" TEXT NOT NULL,\n'
        '  "confidence" TEXT NOT NULL,\n'
        '  "early_warning" INTEGER NOT NULL,\n'
        '  "narrative" TEXT NOT NULL,\n'
        '  "root_causes" TEXT NOT NULL,\n'
        '  "actions" TEXT NOT NULL,\n'
        '  "tier" TEXT NOT NULL,\n'
        '  "model" TEXT,\n'
        '  "cached" INTEGER NOT NULL,\n'
        '  "ai_call_id" TEXT\n'
        ")"
    ),
    'CREATE INDEX "zone_assessments_zone_at" ON "zone_assessments" ("zone_id", "at" DESC)',
    (
        'CREATE TABLE "ai_calls" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "request_id" TEXT NOT NULL,\n'
        '  "at" TEXT NOT NULL,\n'
        '  "role" TEXT NOT NULL,\n'
        '  "tier" TEXT NOT NULL,\n'
        '  "provider" TEXT NOT NULL,\n'
        '  "model" TEXT,\n'
        '  "key_slot" INTEGER,\n'
        '  "prompt_version" TEXT NOT NULL,\n'
        '  "schema_version" TEXT NOT NULL,\n'
        '  "input_hash" TEXT NOT NULL,\n'
        '  "cache_key" TEXT NOT NULL,\n'
        '  "inputs" TEXT NOT NULL,\n'
        '  "image_refs" TEXT NOT NULL,\n'
        '  "output" TEXT,\n'
        '  "valid" INTEGER,\n'
        '  "latency_ms" INTEGER,\n'
        '  "status" TEXT NOT NULL,\n'
        '  "error" TEXT,\n'
        '  "fallback_from" TEXT,\n'
        '  "cache_hit" INTEGER NOT NULL\n'
        ")"
    ),
    'CREATE INDEX "ai_calls_at" ON "ai_calls" ("at" DESC)',
    'CREATE INDEX "ai_calls_cache_key" ON "ai_calls" ("cache_key")',
    (
        'CREATE TABLE "history_series" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "generation_id" TEXT NOT NULL,\n'
        '  "site_id" TEXT NOT NULL,\n'
        '  "zone_id" TEXT NOT NULL,\n'
        '  "year" INTEGER NOT NULL,\n'
        '  "metrics" TEXT NOT NULL,\n'
        '  "ai_call_id" TEXT,\n'
        '  "label" TEXT NOT NULL,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  UNIQUE ("generation_id", "zone_id", "year")\n'
        ")"
    ),
    (
        'CREATE TABLE "restoration_plans" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "plan_id" TEXT NOT NULL,\n'
        '  "version" INTEGER NOT NULL,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  "source" TEXT NOT NULL,\n'
        '  "status" TEXT NOT NULL,\n'
        '  "items" TEXT NOT NULL,\n'
        '  "applied_at" TEXT,\n'
        '  "capture_at_application_id" TEXT,\n'
        '  "forecast_id" TEXT,\n'
        '  "ai_call_id" TEXT,\n'
        '  UNIQUE ("plan_id", "version")\n'
        ")"
    ),
    (
        'CREATE TABLE "forecasts" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  "status" TEXT NOT NULL,\n'
        '  "plan_version_id" TEXT,\n'
        '  "base_capture_id" TEXT NOT NULL,\n'
        '  "input_hash" TEXT NOT NULL,\n'
        '  "parameters" TEXT NOT NULL,\n'
        '  "parameter_sources" TEXT NOT NULL,\n'
        '  "keyframes" TEXT NOT NULL,\n'
        '  "summary" TEXT NOT NULL,\n'
        '  "bands" TEXT NOT NULL\n'
        ")"
    ),
    (
        'CREATE TABLE "illustrations" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "forecast_id" TEXT NOT NULL,\n'
        '  "year" INTEGER NOT NULL,\n'
        '  "scenario" TEXT NOT NULL,\n'
        '  "media_key" TEXT,\n'
        '  "provider" TEXT NOT NULL,\n'
        '  "model" TEXT NOT NULL,\n'
        '  "instruction" TEXT NOT NULL,\n'
        '  "seed" INTEGER NOT NULL,\n'
        '  "status" TEXT NOT NULL,\n'
        '  "cache_key" TEXT NOT NULL,\n'
        '  "error" TEXT,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  "updated_at" TEXT NOT NULL\n'
        ")"
    ),
    (
        'CREATE TABLE "ledger_records" (\n'
        '  "chain_index" INTEGER PRIMARY KEY,\n'
        '  "record_id" TEXT NOT NULL,\n'
        '  "type" TEXT NOT NULL,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  "site_id" TEXT NOT NULL,\n'
        '  "zone_ids" TEXT NOT NULL,\n'
        '  "period" TEXT NOT NULL,\n'
        '  "quantity_tco2e" TEXT NOT NULL,\n'
        '  "gross_tco2e" TEXT NOT NULL,\n'
        '  "deductions" TEXT NOT NULL,\n'
        '  "evidence" TEXT NOT NULL,\n'
        '  "confidence" TEXT NOT NULL,\n'
        '  "method_note" TEXT NOT NULL,\n'
        '  "label" TEXT NOT NULL,\n'
        '  "projected_record_id" TEXT,\n'
        '  "canonical" TEXT NOT NULL,\n'
        '  "previous_hash" TEXT NOT NULL,\n'
        '  "hash" TEXT NOT NULL,\n'
        '  UNIQUE ("record_id"),\n'
        '  UNIQUE ("hash")\n'
        ")"
    ),
    (
        'CREATE TABLE "evidence_packs" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "record_id" TEXT NOT NULL,\n'
        '  "media_key" TEXT NOT NULL,\n'
        '  "generated_at" TEXT NOT NULL,\n'
        '  "chain_intact" INTEGER NOT NULL,\n'
        '  "bytes" INTEGER NOT NULL\n'
        ")"
    ),
    (
        'CREATE TABLE "alerts" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "at" TEXT NOT NULL,\n'
        '  "last_seen_at" TEXT NOT NULL,\n'
        '  "occurrences" INTEGER NOT NULL,\n'
        '  "type" TEXT NOT NULL,\n'
        '  "severity" TEXT NOT NULL,\n'
        '  "zone_id" TEXT,\n'
        '  "node_id" TEXT,\n'
        '  "message" TEXT NOT NULL,\n'
        '  "dedupe_key" TEXT NOT NULL,\n'
        '  "details" TEXT NOT NULL,\n'
        '  "acknowledged_at" TEXT\n'
        ")"
    ),
    'CREATE INDEX "alerts_at" ON "alerts" ("at" DESC)',
    (
        'CREATE TABLE "sim_sessions" (\n'
        '  "id" TEXT PRIMARY KEY,\n'
        '  "created_at" TEXT NOT NULL,\n'
        '  "name" TEXT NOT NULL,\n'
        '  "kind" TEXT NOT NULL,\n'
        '  "seed" INTEGER,\n'
        '  "duration_s" REAL NOT NULL,\n'
        '  "message_count" INTEGER NOT NULL,\n'
        '  "media_key" TEXT NOT NULL\n'
        ")"
    ),
    (
        'CREATE TABLE "system_heartbeats" (\n'
        '  "component" TEXT PRIMARY KEY,\n'
        '  "at" TEXT NOT NULL,\n'
        '  "status" TEXT NOT NULL,\n'
        '  "details" TEXT NOT NULL\n'
        ")"
    ),
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
    (
        'CREATE TABLE "media_objects" (\n'
        '  "bucket" TEXT NOT NULL,\n'
        '  "key" TEXT NOT NULL,\n'
        '  "local_path" TEXT NOT NULL,\n'
        '  "content_type" TEXT NOT NULL,\n'
        '  "bytes" INTEGER NOT NULL,\n'
        '  "protected" INTEGER NOT NULL DEFAULT 0,\n'
        "  \"state\" TEXT NOT NULL CHECK (\"state\" IN ('pending', 'uploaded', 'pruned', 'failed', 'local_only')),\n"
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
)

V1_SQL = ";\n".join(V1_STATEMENTS)
