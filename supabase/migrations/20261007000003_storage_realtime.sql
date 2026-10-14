-- Realtime publication and private storage buckets (addendum H4).

do $$
declare t text;
begin
  foreach t in array array['telemetry', 'alerts', 'zone_assessments', 'tasks', 'captures', 'ledger_records', 'system_heartbeats'] loop
    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t
    ) then
      execute format('alter publication supabase_realtime add table public.%I', t);
    end if;
  end loop;
end;
$$;

insert into storage.buckets (id, name, public, file_size_limit) values
  ('captures', 'captures', false, 20971520),
  ('futures', 'futures', false, 20971520),
  ('evidence-packs', 'evidence-packs', false, 20971520),
  ('sim-sessions', 'sim-sessions', false, 20971520)
on conflict (id) do nothing;
