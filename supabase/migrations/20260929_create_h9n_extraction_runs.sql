-- H9N Milestone 1.3: persist every deal extraction run so any Deal Profile can
-- be traced back to the model, prompt, and exact input that produced it, plus
-- the page-level evidence behind each important field. Depends on
-- 20260921_create_h9n_rag.sql for organizations and is_active_org_member().

-- One row per extraction attempt, successful or not. Rows are append-only: a
-- re-extraction creates a new run, which is what lets versions be compared.
create table if not exists public.extraction_runs (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references public.organizations(id) on delete cascade,
    deal_id uuid not null,
    status text not null check (status in ('succeeded', 'failed')),

    -- Reproducibility: what ran, and over exactly which input.
    model text not null check (char_length(model) > 0),
    prompt_sha256 text not null check (char_length(prompt_sha256) = 64),
    source_filename text not null,
    -- Hash of the uploaded PDF bytes; matches rag_documents.content_sha256
    -- when the same PDF was also indexed for retrieval.
    source_sha256 text not null check (char_length(source_sha256) = 64),
    -- Hash of the page-preserved text actually sent to the model.
    input_sha256 text not null check (char_length(input_sha256) = 64),
    page_count integer not null check (page_count > 0),

    -- The validated REPEDealProfile snapshot, including its missing,
    -- conflicting, and uncertain notes. Only validated output is ever stored.
    profile jsonb,
    error_type text,
    error_message text,

    started_at timestamptz not null,
    completed_at timestamptz not null,
    latency_ms integer not null check (latency_ms >= 0),
    created_at timestamptz not null default now(),

    check (completed_at >= started_at),
    check (
        (status = 'succeeded' and profile is not null and error_type is null)
        or (status = 'failed' and profile is null and error_type is not null)
    ),
    -- Lets child rows use a composite key so they can never point at a run
    -- owned by a different organization.
    unique (id, organization_id)
);

-- One row per evidence citation in a successful run's profile. Stored
-- relationally so reviewers and the evaluation command can query which pages
-- supported which fields without unpacking every profile snapshot.
create table if not exists public.extraction_evidence (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null,
    run_id uuid not null,
    field_name text not null check (char_length(field_name) > 0),
    value text,
    source_document text,
    page_number integer check (page_number > 0),
    snippet text,
    created_at timestamptz not null default now(),
    foreign key (run_id, organization_id)
        references public.extraction_runs(id, organization_id) on delete cascade
);

create index if not exists extraction_runs_organization_deal_idx
    on public.extraction_runs (organization_id, deal_id, created_at desc);
create index if not exists extraction_runs_source_idx
    on public.extraction_runs (organization_id, source_sha256);
create index if not exists extraction_evidence_run_idx
    on public.extraction_evidence (run_id, field_name);

alter table public.extraction_runs enable row level security;
alter table public.extraction_evidence enable row level security;

-- Browser clients may only read their tenant's runs; writes stay server-side
-- and there are deliberately no update or delete grants, keeping runs
-- append-only for everyone except the service role.
revoke all on public.extraction_runs, public.extraction_evidence from anon;
revoke all on public.extraction_runs, public.extraction_evidence from authenticated;
grant select on public.extraction_runs, public.extraction_evidence to authenticated;
grant all privileges on public.extraction_runs, public.extraction_evidence to service_role;

create policy "organization members can read extraction runs"
    on public.extraction_runs for select to authenticated
    using (public.is_active_org_member(organization_id));

create policy "organization members can read extraction evidence"
    on public.extraction_evidence for select to authenticated
    using (public.is_active_org_member(organization_id));

-- Records a run and its evidence in one transaction, so a run can never exist
-- without the evidence it was saved with. Evidence rows are read from the
-- profile itself rather than passed separately, so the two cannot disagree.
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

    return new_run_id;
end;
$$;

revoke all on function public.record_extraction_run(jsonb) from public;
revoke all on function public.record_extraction_run(jsonb) from anon, authenticated;
grant execute on function public.record_extraction_run(jsonb) to service_role;
