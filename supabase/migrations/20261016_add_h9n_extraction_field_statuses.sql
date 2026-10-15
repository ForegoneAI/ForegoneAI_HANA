-- H9N Milestone 1.2: field trust statuses for every extraction run.
--
-- Every saved profile already carries `field_statuses` - one status per value
-- field: supported, uncertain, missing or conflicting (see
-- backend/app/h9n/schemas/field_status.py). This stores them relationally
-- too, one row per field per successful run, the same way
-- extraction_evidence stores citations, so the team can query which fields
-- needed a human (and how that changes between prompt or model versions)
-- without unpacking every profile snapshot. Conflicting passages themselves
-- stay in the profile snapshot, under withheld_values[].conflicting_values.
--
-- These rows are a record of the extraction, like the run they belong to:
-- append-only, never updated when a reviewer later corrects the deal. A
-- deal's current statuses are always computed from its current profile.

create table if not exists public.extraction_field_statuses (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null,
    run_id uuid not null,
    field_name text not null check (char_length(field_name) > 0),
    status text not null check (status in ('supported', 'uncertain', 'missing', 'conflicting')),
    needs_review boolean not null,
    -- FieldStatusReason codes, most specific first, e.g. {conflicting_values}.
    reason_codes text[] not null default '{}',
    -- How many passages a conflict found (0 unless status = 'conflicting').
    conflicting_passage_count integer not null default 0 check (conflicting_passage_count >= 0),
    created_at timestamptz not null default now(),
    unique (run_id, field_name),
    foreign key (run_id, organization_id)
        references public.extraction_runs(id, organization_id) on delete cascade
);

create index if not exists extraction_field_statuses_org_field_idx
    on public.extraction_field_statuses (organization_id, field_name, status);

alter table public.extraction_field_statuses enable row level security;

-- Same access as extraction_evidence: members read their own organization's
-- rows; only the server (service role) writes, through record_extraction_run.
revoke all on public.extraction_field_statuses from anon;
revoke all on public.extraction_field_statuses from authenticated;
grant select on public.extraction_field_statuses to authenticated;
grant all privileges on public.extraction_field_statuses to service_role;

create policy "organization members can read extraction field statuses"
    on public.extraction_field_statuses for select to authenticated
    using (public.is_active_org_member(organization_id));

-- Unchanged from 20260929_create_h9n_extraction_runs.sql except for the last
-- insert: a run, its evidence and its field statuses are saved in one
-- transaction, all read from the profile itself so they cannot disagree.
-- A profile saved before Milestone 1.2 has no field_statuses and records
-- none.
create or replace function public.record_extraction_run(run jsonb)
returns uuid
language plpgsql
set search_path = public
as $$
declare
    new_run_id uuid;
    run_organization_id uuid := (run->>'organization_id')::uuid;
begin
    insert into public.extraction_runs (
        organization_id, deal_id, status, model, prompt_sha256,
        source_filename, source_sha256, input_sha256, page_count,
        profile, error_type, error_message,
        started_at, completed_at, latency_ms
    )
    values (
        run_organization_id,
        (run->>'deal_id')::uuid,
        run->>'status',
        run->>'model',
        run->>'prompt_sha256',
        run->>'source_filename',
        run->>'source_sha256',
        run->>'input_sha256',
        (run->>'page_count')::integer,
        case when jsonb_typeof(run->'profile') = 'object' then run->'profile' end,
        run->>'error_type',
        run->>'error_message',
        (run->>'started_at')::timestamptz,
        (run->>'completed_at')::timestamptz,
        (run->>'latency_ms')::integer
    )
    returning id into new_run_id;

    insert into public.extraction_evidence (
        organization_id, run_id, field_name, value, source_document, page_number, snippet
    )
    select
        run_organization_id,
        new_run_id,
        evidence.field_name,
        evidence.value,
        evidence.source_document,
        evidence.page_number,
        evidence.snippet
    from jsonb_to_recordset(coalesce(run->'profile'->'evidence', '[]'::jsonb)) as evidence(
        field_name text,
        value text,
        source_document text,
        page_number integer,
        snippet text
    );

    insert into public.extraction_field_statuses (
        organization_id, run_id, field_name, status, needs_review, reason_codes, conflicting_passage_count
    )
    select
        run_organization_id,
        new_run_id,
        statuses.key,
        statuses.value->>'status',
        (statuses.value->>'needs_review')::boolean,
        coalesce(
            array(
                select reason->>'code'
                from jsonb_array_elements(coalesce(statuses.value->'reasons', '[]'::jsonb)) as reason
            ),
            '{}'
        ),
        jsonb_array_length(coalesce(statuses.value->'conflicting_values', '[]'::jsonb))
    from jsonb_each(
        case
            when jsonb_typeof(run->'profile'->'field_statuses') = 'object' then run->'profile'->'field_statuses'
            else '{}'::jsonb
        end
    ) as statuses;

    return new_run_id;
end;
$$;

revoke all on function public.record_extraction_run(jsonb) from public;
revoke all on function public.record_extraction_run(jsonb) from anon, authenticated;
grant execute on function public.record_extraction_run(jsonb) to service_role;
