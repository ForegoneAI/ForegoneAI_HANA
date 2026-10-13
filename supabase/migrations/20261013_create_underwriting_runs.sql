-- M4: append-only underwriting versions. Input provenance, scenario assumptions,
-- and derived outputs are stored as distinct JSONB columns.
create table if not exists public.underwriting_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  deal_id text not null,
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  inputs jsonb not null,
  scenario_assumptions jsonb not null,
  results jsonb not null
);
create index if not exists underwriting_runs_org_deal_idx on public.underwriting_runs(organization_id,deal_id,created_at desc);
alter table public.underwriting_runs enable row level security;
revoke all on public.underwriting_runs from anon, authenticated;
grant select on public.underwriting_runs to authenticated;
grant all on public.underwriting_runs to service_role;
create policy "members read own underwriting" on public.underwriting_runs
  for select to authenticated using (public.is_active_org_member(organization_id));
