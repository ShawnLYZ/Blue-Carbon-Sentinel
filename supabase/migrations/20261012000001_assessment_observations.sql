-- M4 task 11: the zone's VisionAnalyst observations on its assessment ({"items": [...], "source": chip|null}).
alter table public.zone_assessments add column "observations" jsonb;
