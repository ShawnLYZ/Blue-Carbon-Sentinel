-- Row-level security, anonymous read policy, write revocation (addendum H4).

alter table public.sites enable row level security;
alter table public.zones enable row level security;
alter table public.calibrations enable row level security;
alter table public.devices enable row level security;
alter table public.device_keys enable row level security;
alter table public.device_history enable row level security;
alter table public.commissioning_runs enable row level security;
alter table public.telemetry enable row level security;
alter table public.node_events enable row level security;
alter table public.tasks enable row level security;
alter table public.commands enable row level security;
alter table public.captures enable row level security;
alter table public.zone_metrics enable row level security;
alter table public.tree_points enable row level security;
alter table public.zone_assessments enable row level security;
alter table public.ai_calls enable row level security;
alter table public.history_series enable row level security;
alter table public.restoration_plans enable row level security;
alter table public.forecasts enable row level security;
alter table public.illustrations enable row level security;
alter table public.ledger_records enable row level security;
alter table public.evidence_packs enable row level security;
alter table public.alerts enable row level security;
alter table public.sim_sessions enable row level security;
alter table public.system_heartbeats enable row level security;

create policy anon_read_sites on public.sites for select to anon using (true);
create policy anon_read_zones on public.zones for select to anon using (true);
create policy anon_read_calibrations on public.calibrations for select to anon using (true);
create policy anon_read_devices on public.devices for select to anon using (true);
create policy anon_read_device_history on public.device_history for select to anon using (true);
create policy anon_read_commissioning_runs on public.commissioning_runs for select to anon using (true);
create policy anon_read_telemetry on public.telemetry for select to anon using (true);
create policy anon_read_node_events on public.node_events for select to anon using (true);
create policy anon_read_tasks on public.tasks for select to anon using (true);
create policy anon_read_commands on public.commands for select to anon using (true);
create policy anon_read_captures on public.captures for select to anon using (true);
create policy anon_read_zone_metrics on public.zone_metrics for select to anon using (true);
create policy anon_read_tree_points on public.tree_points for select to anon using (true);
create policy anon_read_zone_assessments on public.zone_assessments for select to anon using (true);
create policy anon_read_ai_calls on public.ai_calls for select to anon using (true);
create policy anon_read_history_series on public.history_series for select to anon using (true);
create policy anon_read_restoration_plans on public.restoration_plans for select to anon using (true);
create policy anon_read_forecasts on public.forecasts for select to anon using (true);
create policy anon_read_illustrations on public.illustrations for select to anon using (true);
create policy anon_read_ledger_records on public.ledger_records for select to anon using (true);
create policy anon_read_evidence_packs on public.evidence_packs for select to anon using (true);
create policy anon_read_alerts on public.alerts for select to anon using (true);
create policy anon_read_sim_sessions on public.sim_sessions for select to anon using (true);
create policy anon_read_system_heartbeats on public.system_heartbeats for select to anon using (true);

revoke all on public.sites from anon, authenticated;
revoke all on public.zones from anon, authenticated;
revoke all on public.calibrations from anon, authenticated;
revoke all on public.devices from anon, authenticated;
revoke all on public.device_keys from anon, authenticated;
revoke all on public.device_history from anon, authenticated;
revoke all on public.commissioning_runs from anon, authenticated;
revoke all on public.telemetry from anon, authenticated;
revoke all on public.node_events from anon, authenticated;
revoke all on public.tasks from anon, authenticated;
revoke all on public.commands from anon, authenticated;
revoke all on public.captures from anon, authenticated;
revoke all on public.zone_metrics from anon, authenticated;
revoke all on public.tree_points from anon, authenticated;
revoke all on public.zone_assessments from anon, authenticated;
revoke all on public.ai_calls from anon, authenticated;
revoke all on public.history_series from anon, authenticated;
revoke all on public.restoration_plans from anon, authenticated;
revoke all on public.forecasts from anon, authenticated;
revoke all on public.illustrations from anon, authenticated;
revoke all on public.ledger_records from anon, authenticated;
revoke all on public.evidence_packs from anon, authenticated;
revoke all on public.alerts from anon, authenticated;
revoke all on public.sim_sessions from anon, authenticated;
revoke all on public.system_heartbeats from anon, authenticated;

grant select on public.sites to anon;
grant select on public.zones to anon;
grant select on public.calibrations to anon;
grant select on public.devices to anon;
grant select on public.device_history to anon;
grant select on public.commissioning_runs to anon;
grant select on public.telemetry to anon;
grant select on public.node_events to anon;
grant select on public.tasks to anon;
grant select on public.commands to anon;
grant select on public.captures to anon;
grant select on public.zone_metrics to anon;
grant select on public.tree_points to anon;
grant select on public.zone_assessments to anon;
grant select on public.ai_calls to anon;
grant select on public.history_series to anon;
grant select on public.restoration_plans to anon;
grant select on public.forecasts to anon;
grant select on public.illustrations to anon;
grant select on public.ledger_records to anon;
grant select on public.evidence_packs to anon;
grant select on public.alerts to anon;
grant select on public.sim_sessions to anon;
grant select on public.system_heartbeats to anon;

-- device_keys keeps no grants for anon/authenticated (A8); the revoke above stands.

-- Ledger is append-only for every role (A5, H4).
create function public.bcs_ledger_immutable() returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'ledger_records is append-only: % rejected', tg_op using errcode = 'P0001';
end;
$$;

create trigger bcs_ledger_immutable
  before update or delete on public.ledger_records
  for each row execute function public.bcs_ledger_immutable();

create trigger bcs_ledger_immutable_truncate
  before truncate on public.ledger_records
  for each statement execute function public.bcs_ledger_immutable();

-- Database size helper for preflight and the System page (A2).
create function public.bcs_db_size() returns bigint
language sql
security definer
set search_path = ''
as $$ select pg_database_size(current_database()) $$;

revoke all on function public.bcs_db_size() from public, anon, authenticated;
grant execute on function public.bcs_db_size() to service_role;
