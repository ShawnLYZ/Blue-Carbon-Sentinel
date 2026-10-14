-- Core schema: 25 synced tables (addendum H1/H2). Generated from bcs_gs.store.schema.SYNCED_TABLES;
-- Postgres keeps keys and checks only, no cross-table constraints (H1). Enum CHECK lists come from F5.

create table public.sites (
  "id" text primary key,
  "name" text not null,
  "status" text not null,
  "region" text not null,
  "centre_lat" float8 not null,
  "centre_lng" float8 not null,
  "anchor_nw_lat" float8,
  "anchor_nw_lng" float8,
  "bearing_deg" float8 not null,
  "size_m" float8,
  "scale_label" text,
  "rationale" text not null,
  "updated_at" timestamptz not null,
  constraint sites_status_check check ("status" in ('live', 'planned'))
);

create table public.zones (
  "id" text primary key,
  "site_id" text not null,
  "label" text not null,
  "coordinate_id" text not null,
  "col" int2 not null,
  "row" int2 not null,
  "bounds" jsonb not null,
  "bounds_site_m" jsonb not null,
  "centre_lat" float8 not null,
  "centre_lng" float8 not null,
  "area_ha" float8 not null,
  unique ("coordinate_id"),
  constraint zones_col_range check ("col" between 0 and 4),
  constraint zones_row_range check ("row" between 0 and 4)
);

create table public.calibrations (
  "id" uuid primary key,
  "created_at" timestamptz not null,
  "mode" text not null,
  "frame_w" int4 not null,
  "frame_h" int4 not null,
  "corners_px" jsonb,
  "north_edge" int2,
  "homography" jsonb not null,
  "active" bool not null,
  constraint calibrations_mode_check check ("mode" in ('default', 'four_corner'))
);
create unique index "calibrations_one_active" on public.calibrations ("active") where "active";

create table public.devices (
  "id" text primary key,
  "kind" text not null,
  "node_type" text,
  "source" text not null,
  "site_id" text not null,
  "e_m" float8,
  "s_m" float8,
  "lat" float8,
  "lng" float8,
  "u_px" float8,
  "v_px" float8,
  "zone_id" text,
  "status" text not null,
  "mode" text,
  "interval_s" int4,
  "fw_version" text,
  "boot_id" text,
  "installed_at" timestamptz,
  "decommissioned_at" timestamptz,
  "last_seen_at" timestamptz,
  "commissioning_run_id" uuid,
  "updated_at" timestamptz not null,
  constraint devices_kind_check check ("kind" in ('sentinel_node', 'camera')),
  constraint devices_node_type_check check ("node_type" in ('water_quality', 'soil_probe', 'tide_gauge')),
  constraint devices_source_check check ("source" in ('simulated', 'hardware')),
  constraint devices_status_check check ("status" in ('online', 'offline', 'unknown', 'decommissioned')),
  constraint devices_mode_check check ("mode" in ('baseline', 'investigation'))
);

create table public.device_keys (
  "device_id" text primary key,
  "key_hash" text not null,
  "created_at" timestamptz not null,
  "rotations" int4 not null
);

create table public.device_history (
  "id" uuid primary key,
  "device_id" text not null,
  "at" timestamptz not null,
  "change" text not null,
  "details" jsonb not null,
  constraint device_history_change_check check ("change" in ('installed', 'moved', 're_commissioned', 'decommissioned', 'key_regenerated'))
);

create table public.commissioning_runs (
  "id" uuid primary key,
  "created_at" timestamptz not null,
  "capture_id" uuid,
  "method" text not null,
  "confidence" text not null,
  "reasons" jsonb not null,
  "positions" jsonb not null,
  "coverage" jsonb not null,
  "seed" int4 not null,
  constraint commissioning_runs_method_check check ("method" in ('class_map', 'fallback_spread')),
  constraint commissioning_runs_confidence_check check ("confidence" in ('high', 'low'))
);

create table public.telemetry (
  "id" uuid primary key,
  "node_id" text not null,
  "boot_id" text not null,
  "seq" int8 not null,
  "sampled_at" timestamptz not null,
  "received_at" timestamptz not null,
  "mode" text not null,
  "readings" jsonb not null,
  "health" jsonb not null,
  "flags" jsonb not null,
  "source" text not null,
  "replay" bool not null,
  "late" bool not null,
  unique ("node_id", "boot_id", "seq"),
  constraint telemetry_mode_check check ("mode" in ('baseline', 'investigation')),
  constraint telemetry_source_check check ("source" in ('simulated', 'hardware'))
);
create index "telemetry_node_sampled" on public.telemetry ("node_id", "sampled_at" desc);

create table public.node_events (
  "id" uuid primary key,
  "node_id" text not null,
  "at" timestamptz not null,
  "origin" text not null,
  "kind" text not null,
  "parameter" text,
  "value" float8,
  "score" float8,
  "details" jsonb not null,
  "boot_id" text,
  "seq" int8,
  constraint node_events_origin_check check ("origin" in ('node', 'ground_station')),
  constraint node_events_kind_check check ("kind" in ('anomaly', 'threshold', 'stuck', 'battery_low', 'boot', 'config_applied', 'malformed_input', 'malformed', 'offline', 'online'))
);
create index "node_events_node_at" on public.node_events ("node_id", "at" desc);
create unique index "node_events_node_seq" on public.node_events ("node_id", "boot_id", "seq") where "origin" = 'node';

create table public.tasks (
  "id" uuid primary key,
  "created_at" timestamptz not null,
  "updated_at" timestamptz not null,
  "expires_at" timestamptz not null,
  "trigger" text not null,
  "zone_id" text,
  "node_ids" jsonb not null,
  "mode" text not null,
  "duration_s" int4 not null,
  "status" text not null,
  "reason" text not null,
  "cancelled_by" text,
  "timeline" jsonb not null,
  constraint tasks_trigger_check check ("trigger" in ('zone_flag', 'node_anomaly', 'risk_high', 'early_warning', 'manual')),
  constraint tasks_mode_check check ("mode" in ('investigation')),
  constraint tasks_status_check check ("status" in ('issued', 'active', 'completed', 'cancelled', 'expired')),
  constraint tasks_cancelled_by_check check ("cancelled_by" in ('operator'))
);

create table public.commands (
  "id" uuid primary key,
  "task_id" uuid,
  "node_id" text not null,
  "type" text not null,
  "params" jsonb not null,
  "issued_at" timestamptz not null,
  "expires_at" timestamptz,
  "ack_status" text not null,
  "ack_at" timestamptz,
  "retries" int2 not null,
  constraint commands_type_check check ("type" in ('set_mode', 'set_config', 'ping', 'reboot')),
  constraint commands_ack_status_check check ("ack_status" in ('pending', 'accepted', 'rejected', 'completed', 'expired', 'no_ack', 'released'))
);

create table public.captures (
  "id" uuid primary key,
  "taken_at" timestamptz not null,
  "trigger" text not null,
  "imagery_source" text not null,
  "bands" jsonb not null,
  "calibration_id" uuid not null,
  "frame_seq" int8 not null,
  "media" jsonb not null,
  "media_state" text not null,
  "quality" jsonb not null,
  "evidence_grade" bool not null,
  "is_baseline" bool not null,
  "flagged" bool not null,
  "change_score" float8,
  "retention_reason" text,
  constraint captures_trigger_check check ("trigger" in ('interval', 'change', 'manual')),
  constraint captures_imagery_source_check check ("imagery_source" in ('esp32cam', 'sentinel2')),
  constraint captures_media_state_check check ("media_state" in ('local', 'uploaded', 'pruned')),
  constraint captures_retention_reason_check check ("retention_reason" in ('baseline', 'plan_application', 'referenced', 'ledger_evidence'))
);
create index "captures_taken_at" on public.captures ("taken_at" desc);

create table public.zone_metrics (
  "capture_id" uuid,
  "zone_id" text,
  "canopy_pct" float8 not null,
  "water_pct" float8 not null,
  "mud_pct" float8 not null,
  "other_pct" float8 not null,
  "vari_mean" float8,
  "vari_p10" float8,
  "vari_p90" float8,
  "canopy_loss_pp" float8,
  "vari_drop" float8,
  "dieback_pct" float8 not null,
  "new_growth_pct" float8 not null,
  "discolouration" float8,
  "flags" jsonb not null,
  primary key ("capture_id", "zone_id")
);
create index "zone_metrics_zone" on public.zone_metrics ("zone_id");

create table public.tree_points (
  "id" uuid primary key,
  "capture_id" uuid not null,
  "created_at" timestamptz not null,
  "points" jsonb not null,
  "tier" text not null,
  "model" text,
  "ai_call_id" uuid,
  constraint tree_points_tier_check check ("tier" in ('robotics_er', 'gemini_primary', 'gemini_secondary', 'gemma_local', 'rules'))
);

create table public.zone_assessments (
  "id" uuid primary key,
  "zone_id" text not null,
  "at" timestamptz not null,
  "capture_id" uuid,
  "stressors" jsonb not null,
  "multipliers" jsonb not null,
  "weights" jsonb not null,
  "risk_score" float8 not null,
  "risk_class" text not null,
  "confidence" jsonb not null,
  "early_warning" bool not null,
  "narrative" text not null,
  "root_causes" jsonb not null,
  "actions" jsonb not null,
  "tier" text not null,
  "model" text,
  "cached" bool not null,
  "ai_call_id" uuid,
  constraint zone_assessments_risk_class_check check ("risk_class" in ('low', 'medium', 'high', 'critical')),
  constraint zone_assessments_tier_check check ("tier" in ('robotics_er', 'gemini_primary', 'gemini_secondary', 'gemma_local', 'rules'))
);
create index "zone_assessments_zone_at" on public.zone_assessments ("zone_id", "at" desc);

create table public.ai_calls (
  "id" uuid primary key,
  "request_id" uuid not null,
  "at" timestamptz not null,
  "role" text not null,
  "tier" text not null,
  "provider" text not null,
  "model" text,
  "key_slot" int2,
  "prompt_version" text not null,
  "schema_version" text not null,
  "input_hash" text not null,
  "cache_key" text not null,
  "inputs" jsonb not null,
  "image_refs" jsonb not null,
  "output" jsonb,
  "valid" bool,
  "latency_ms" int4,
  "status" text not null,
  "error" text,
  "fallback_from" uuid,
  "cache_hit" bool not null,
  constraint ai_calls_role_check check ("role" in ('vision_analyst', 'tree_locator', 'risk_interpreter', 'forecast_parameter_estimator', 'restoration_planner', 'history_synthesizer')),
  constraint ai_calls_tier_check check ("tier" in ('robotics_er', 'gemini_primary', 'gemini_secondary', 'gemma_local', 'rules')),
  constraint ai_calls_status_check check ("status" in ('success', 'cache_hit', 'rate_limited', 'overloaded', 'timeout', 'invalid_output', 'unavailable', 'error', 'skipped')),
  constraint ai_calls_key_slot_range check ("key_slot" between 1 and 3)
);
create index "ai_calls_at" on public.ai_calls ("at" desc);
create index "ai_calls_cache_key" on public.ai_calls ("cache_key");

create table public.history_series (
  "id" uuid primary key,
  "generation_id" uuid not null,
  "site_id" text not null,
  "zone_id" text not null,
  "year" int2 not null,
  "metrics" jsonb not null,
  "ai_call_id" uuid,
  "label" text not null,
  "created_at" timestamptz not null,
  unique ("generation_id", "zone_id", "year"),
  constraint history_series_year_range check ("year" between 2016 and 2025)
);

create table public.restoration_plans (
  "id" uuid primary key,
  "plan_id" uuid not null,
  "version" int4 not null,
  "created_at" timestamptz not null,
  "source" text not null,
  "status" text not null,
  "items" jsonb not null,
  "applied_at" timestamptz,
  "capture_at_application_id" uuid,
  "forecast_id" uuid,
  "ai_call_id" uuid,
  unique ("plan_id", "version"),
  constraint restoration_plans_source_check check ("source" in ('ai', 'operator', 'mixed')),
  constraint restoration_plans_status_check check ("status" in ('draft', 'applied', 'superseded'))
);

create table public.forecasts (
  "id" uuid primary key,
  "created_at" timestamptz not null,
  "status" text not null,
  "plan_version_id" uuid,
  "base_capture_id" uuid not null,
  "input_hash" text not null,
  "parameters" jsonb not null,
  "parameter_sources" jsonb not null,
  "keyframes" jsonb not null,
  "summary" jsonb not null,
  "bands" jsonb not null,
  constraint forecasts_status_check check ("status" in ('pending', 'ready', 'failed'))
);

create table public.illustrations (
  "id" uuid primary key,
  "forecast_id" uuid not null,
  "year" int2 not null,
  "scenario" text not null,
  "media_key" text,
  "provider" text not null,
  "model" text not null,
  "instruction" text not null,
  "seed" int4 not null,
  "status" text not null,
  "cache_key" text not null,
  "error" text,
  "created_at" timestamptz not null,
  "updated_at" timestamptz not null,
  constraint illustrations_scenario_check check ("scenario" in ('without', 'with')),
  constraint illustrations_status_check check ("status" in ('pending', 'ready', 'failed', 'skipped')),
  constraint illustrations_year_check check ("year" in (2030, 2035))
);

create table public.ledger_records (
  "chain_index" int8 primary key,
  "record_id" text not null,
  "type" text not null,
  "created_at" timestamptz not null,
  "site_id" text not null,
  "zone_ids" jsonb not null,
  "period" jsonb not null,
  "quantity_tco2e" numeric(14,3) not null,
  "gross_tco2e" numeric(14,3) not null,
  "deductions" jsonb not null,
  "evidence" jsonb not null,
  "confidence" jsonb not null,
  "method_note" text not null,
  "label" text not null,
  "projected_record_id" text,
  "canonical" text not null,
  "previous_hash" char(64) not null,
  "hash" char(64) not null,
  unique ("record_id"),
  unique ("hash"),
  constraint ledger_records_type_check check ("type" in ('projected', 'verified'))
);

create table public.evidence_packs (
  "id" uuid primary key,
  "record_id" text not null,
  "media_key" text not null,
  "generated_at" timestamptz not null,
  "chain_intact" bool not null,
  "bytes" int4 not null
);

create table public.alerts (
  "id" uuid primary key,
  "at" timestamptz not null,
  "last_seen_at" timestamptz not null,
  "occurrences" int4 not null,
  "type" text not null,
  "severity" text not null,
  "zone_id" text,
  "node_id" text,
  "message" text not null,
  "dedupe_key" text not null,
  "details" jsonb not null,
  "acknowledged_at" timestamptz,
  constraint alerts_type_check check ("type" in ('zone_flagged', 'early_warning', 'risk_critical', 'node_anomaly', 'node_offline', 'node_low_battery', 'camera_offline', 'cloud_offline', 'ai_degraded', 'coverage_gap', 'task_started', 'task_ended', 'ledger_issued', 'chain_broken', 'camera_online')),
  constraint alerts_severity_check check ("severity" in ('info', 'warning', 'critical'))
);
create index "alerts_at" on public.alerts ("at" desc);

create table public.sim_sessions (
  "id" uuid primary key,
  "created_at" timestamptz not null,
  "name" text not null,
  "kind" text not null,
  "seed" int4,
  "duration_s" float8 not null,
  "message_count" int4 not null,
  "media_key" text not null,
  constraint sim_sessions_kind_check check ("kind" in ('recording', 'scenario_run'))
);

create table public.system_heartbeats (
  "component" text primary key,
  "at" timestamptz not null,
  "status" text not null,
  "details" jsonb not null,
  constraint system_heartbeats_status_check check ("status" in ('ok', 'warn', 'fail', 'off'))
);
