-- H9N Milestone 3.1: investment mandates - each organization's explicit,
-- editable screening criteria (asset types, geography, deal size, key
-- metrics, leverage limits, soft preferences). The criteria are validated in
-- Python (backend/app/h9n/screening/mandate.py) before they are saved, and
-- stored here as one JSON document so the form can grow without migrations.
-- Depends on 20260921_create_h9n_rag.sql for organizations and
-- is_active_org_member().

create table if not exists public.investment_mandates (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references public.organizations(id) on delete cascade,
    name text not null check (char_length(name) between 1 and 120),
    description text check (description is null or char_length(description) <= 2000),
    criteria jsonb not null check (jsonb_typeof(criteria) = 'object'),
    -- Example mandates (like the built-in demo) are flagged so nobody mistakes
    -- them for a real fund's policy.
    is_demo boolean not null default false,
    -- Archived mandates are kept, not deleted, so past screenings can still
    -- show the criteria they were judged against. They can't be selected for
    -- new screenings.
    is_archived boolean not null default false,
    -- Goes up by one on every edit; screening results record it, and edits
    -- must name the version they started from (see the repository).
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id, organization_id)
);

-- Two active mandates in one organization can't share a name (ignoring
-- case), so "select the mandate called X" is never ambiguous. Archived ones
-- free their name up again.
create unique index if not exists investment_mandates_active_name_idx
    on public.investment_mandates (organization_id, lower(name))
    where not is_archived;

create index if not exists investment_mandates_organization_idx
    on public.investment_mandates (organization_id, is_archived, name);

create or replace function public.set_investment_mandate_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists investment_mandates_set_updated_at on public.investment_mandates;
create trigger investment_mandates_set_updated_at
    before update on public.investment_mandates
    for each row execute function public.set_investment_mandate_updated_at();

alter table public.investment_mandates enable row level security;

-- Same model as extraction runs: signed-in members may read their own
-- organization's mandates; all writes go through the API's server-side
-- service role, which validates them first.
revoke all on public.investment_mandates from anon;
revoke all on public.investment_mandates from authenticated;
grant select on public.investment_mandates to authenticated;
grant all privileges on public.investment_mandates to service_role;

drop policy if exists "organization members can read investment mandates" on public.investment_mandates;
create policy "organization members can read investment mandates"
    on public.investment_mandates for select to authenticated
    using (public.is_active_org_member(organization_id));
