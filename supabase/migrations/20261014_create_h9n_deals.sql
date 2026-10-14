-- H9N Milestone 2.4: saved deals and their review trail.
--
-- A deal is the Deal Profile extracted from one upload plus where it stands
-- in review: draft -> reviewed -> approved. Approved deals are the trusted
-- input to screening and underwriting, so they can't be edited until someone
-- reopens them.
--
-- Nothing a reviewer does is lost: every changed field is kept in
-- deal_corrections (original value, corrected value, the evidence at the
-- time, who, when) and every status change in deal_status_changes. Both are
-- append-only. Changes go through save_deal_changes(), which refuses to
-- overwrite a deal that someone else changed since it was read.
--
-- Depends on 20260921_create_h9n_rag.sql (organizations,
-- is_active_org_member()) and 20260929_create_h9n_extraction_runs.sql.

create table if not exists public.deals (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references public.organizations(id) on delete cascade,
    status text not null default 'draft' check (status in ('draft', 'reviewed', 'approved')),
    -- Goes up by one on every saved change. A change must name the version
    -- it was made against (see save_deal_changes).
    version integer not null default 1 check (version >= 1),

    -- The current REPEDealProfile, validated in Python before it is saved.
    profile jsonb not null check (jsonb_typeof(profile) = 'object'),

    source_filename text not null check (char_length(source_filename) > 0),
    -- The page-preserved text the deal was extracted from, so reviewer
    -- feedback can be checked against the document again later.
    source_pages jsonb check (source_pages is null or jsonb_typeof(source_pages) = 'array'),
    -- The extraction run (Milestone 1.3) that produced the first version.
    extraction_run_id uuid,

    created_by uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    unique (id, organization_id),
    foreign key (extraction_run_id, organization_id)
        references public.extraction_runs(id, organization_id)
);

-- One row per changed field, in the order changes were saved.
create table if not exists public.deal_corrections (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null,
    deal_id uuid not null,
    -- The deal version this change produced.
    deal_version integer not null check (deal_version > 1),
    field_name text not null check (char_length(field_name) > 0),
    original_value jsonb,
    corrected_value jsonb,
    -- The field's source citation when it was changed, so the reviewer's
    -- decision can be checked against what the document actually said.
    evidence jsonb check (evidence is null or jsonb_typeof(evidence) = 'object'),
    -- 'reviewer': typed in by a person. 'reviewer_feedback': re-derived from
    -- the document after a reviewer described what was wrong (`feedback`).
    source text not null check (source in ('reviewer', 'reviewer_feedback')),
    feedback text,
    corrected_by uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    foreign key (deal_id, organization_id)
        references public.deals(id, organization_id) on delete cascade
);

create table if not exists public.deal_status_changes (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null,
    deal_id uuid not null,
    deal_version integer not null check (deal_version > 1),
    -- 'edit' is the automatic move back to draft when a reviewed deal changes.
    action text not null check (action in ('review', 'approve', 'reopen', 'reject', 'edit')),
    from_status text not null check (from_status in ('draft', 'reviewed', 'approved')),
    to_status text not null check (to_status in ('draft', 'reviewed', 'approved')),
    note text,
    changed_by uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    foreign key (deal_id, organization_id)
        references public.deals(id, organization_id) on delete cascade
);

create index if not exists deals_organization_updated_idx
    on public.deals (organization_id, updated_at desc);
create index if not exists deal_corrections_deal_idx
    on public.deal_corrections (deal_id, created_at);
create index if not exists deal_status_changes_deal_idx
    on public.deal_status_changes (deal_id, created_at);

alter table public.deals enable row level security;
alter table public.deal_corrections enable row level security;
alter table public.deal_status_changes enable row level security;

-- Same model as extraction runs and mandates: signed-in members may read
-- their own organization's deals and history; every write goes through the
-- API's server-side service role, which validates it first. There are no
-- update or delete grants, so the history stays append-only.
revoke all on public.deals, public.deal_corrections, public.deal_status_changes from anon;
revoke all on public.deals, public.deal_corrections, public.deal_status_changes from authenticated;
grant select on public.deals, public.deal_corrections, public.deal_status_changes to authenticated;
grant all privileges on public.deals, public.deal_corrections, public.deal_status_changes to service_role;

drop policy if exists "organization members can read deals" on public.deals;
create policy "organization members can read deals"
    on public.deals for select to authenticated
    using (public.is_active_org_member(organization_id));

drop policy if exists "organization members can read deal corrections" on public.deal_corrections;
create policy "organization members can read deal corrections"
    on public.deal_corrections for select to authenticated
    using (public.is_active_org_member(organization_id));

drop policy if exists "organization members can read deal status changes" on public.deal_status_changes;
create policy "organization members can read deal status changes"
    on public.deal_status_changes for select to authenticated
    using (public.is_active_org_member(organization_id));

-- Saves one reviewer action in a single transaction: the new profile and
-- status, plus its corrections and status change. Returns the new version.
--
-- The update only applies if the deal is still at `expected_version`, so two
-- reviewers can't silently overwrite each other. Errors use PostgREST's
-- PTxxx codes, which become that HTTP status: PT409 when the deal changed
-- since it was read, PT404 when it doesn't exist in that organization.
create or replace function public.save_deal_changes(change jsonb)
returns integer
language plpgsql
set search_path = public
as $$
declare
    target_deal_id uuid := (change->>'deal_id')::uuid;
    target_organization_id uuid := (change->>'organization_id')::uuid;
    new_version integer;
begin
    update public.deals
       set profile = change->'profile',
           status = change->>'status',
           version = version + 1,
           updated_at = now()
     where id = target_deal_id
       and organization_id = target_organization_id
       and version = (change->>'expected_version')::integer
    returning version into new_version;

    if new_version is null then
        if exists (
            select 1 from public.deals
            where id = target_deal_id and organization_id = target_organization_id
        ) then
            raise exception 'deal % was changed since version %', target_deal_id, change->>'expected_version'
                using errcode = 'PT409';
        end if;
        raise exception 'deal % not found', target_deal_id using errcode = 'PT404';
    end if;

    insert into public.deal_corrections (
        organization_id, deal_id, deal_version, field_name, original_value,
        corrected_value, evidence, source, feedback, corrected_by
    )
    select
        target_organization_id,
        target_deal_id,
        new_version,
        correction->>'field_name',
        correction->'original_value',
        correction->'corrected_value',
        case when jsonb_typeof(correction->'evidence') = 'object' then correction->'evidence' end,
        correction->>'source',
        correction->>'feedback',
        (correction->>'corrected_by')::uuid
    from jsonb_array_elements(coalesce(change->'corrections', '[]'::jsonb)) as correction;

    if jsonb_typeof(change->'status_change') = 'object' then
        insert into public.deal_status_changes (
            organization_id, deal_id, deal_version, action, from_status, to_status, note, changed_by
        )
        values (
            target_organization_id,
            target_deal_id,
            new_version,
            change->'status_change'->>'action',
            change->'status_change'->>'from_status',
            change->'status_change'->>'to_status',
            change->'status_change'->>'note',
            (change->'status_change'->>'changed_by')::uuid
        );
    end if;

    return new_version;
end;
$$;

revoke all on function public.save_deal_changes(jsonb) from public;
revoke all on function public.save_deal_changes(jsonb) from anon, authenticated;
grant execute on function public.save_deal_changes(jsonb) to service_role;
