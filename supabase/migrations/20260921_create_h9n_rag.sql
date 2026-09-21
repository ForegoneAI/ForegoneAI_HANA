-- H9N RAG foundation: source records stay in ordinary Postgres tables while
-- pgvector holds only searchable passage representations. Apply this migration
-- through the Supabase CLI or SQL Editor before starting the RAG API.

create extension if not exists vector with schema extensions;

-- An organization is the tenant boundary. Customer names are optional to keep
-- the RAG pipeline independent of future CRM/account-management choices.
create table if not exists public.organizations (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    created_at timestamptz not null default now()
);

-- Roles are intentionally minimal for now. A later review UI can add more
-- granular workflow permissions without changing the document ownership key.
create table if not exists public.organization_memberships (
    organization_id uuid not null references public.organizations(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null check (role in ('admin', 'reviewer', 'analyst', 'viewer')),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    primary key (organization_id, user_id)
);

-- Metadata for one indexed source. The raw PDF, when present, stays in a
-- private Storage bucket; it is never stored in the vector table.
create table if not exists public.rag_documents (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references public.organizations(id) on delete cascade,
    deal_id uuid,
    document_name text not null,
    source_type text not null check (
        source_type in ('deal_package', 'analyst_note', 'investment_criteria', 'decision', 'outcome', 'other')
    ),
    content_sha256 text not null check (char_length(content_sha256) = 64),
    page_count integer not null check (page_count > 0),
    is_verified_knowledge boolean not null default false,
    storage_path text unique,
    is_archived boolean not null default false,
    created_at timestamptz not null default now()
);

-- Each chunk is tied to its source page and tenant. Its vector dimension must
-- equal H9N_RAG_EMBEDDING_DIMENSIONS in .env (1536 for the supplied model).
create table if not exists public.rag_chunks (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references public.organizations(id) on delete cascade,
    document_id uuid not null references public.rag_documents(id) on delete cascade,
    deal_id uuid,
    page_number integer not null check (page_number > 0),
    chunk_index integer not null check (chunk_index >= 0),
    content text not null check (char_length(content) > 0),
    embedding extensions.vector(1536) not null,
    embedding_model text not null,
    created_at timestamptz not null default now(),
    unique (document_id, chunk_index)
);

create index if not exists rag_documents_organization_idx
    on public.rag_documents (organization_id, deal_id, is_archived);
create index if not exists rag_chunks_organization_idx
    on public.rag_chunks (organization_id, deal_id, document_id);
create index if not exists rag_chunks_embedding_hnsw_idx
    on public.rag_chunks using hnsw (embedding vector_cosine_ops);

-- This security-definer helper checks memberships without granting users broad
-- read access to the membership table. It is used by every tenant RLS policy.
create or replace function public.is_active_org_member(target_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, auth
as $$
    select exists (
        select 1
        from public.organization_memberships membership
        where membership.organization_id = target_organization_id
          and membership.user_id = (select auth.uid())
          and membership.is_active = true
    );
$$;

revoke all on function public.is_active_org_member(uuid) from public;
grant execute on function public.is_active_org_member(uuid) to authenticated;

alter table public.organizations enable row level security;
alter table public.organization_memberships enable row level security;
alter table public.rag_documents enable row level security;
alter table public.rag_chunks enable row level security;

-- Do not leave auto-generated Data API privileges in place. Browser clients
-- can read only their tenant's records; indexing remains server-side only.
revoke all on public.organizations, public.organization_memberships,
    public.rag_documents, public.rag_chunks from anon;
revoke all on public.organizations, public.organization_memberships,
    public.rag_documents, public.rag_chunks from authenticated;
grant select on public.organizations, public.organization_memberships,
    public.rag_documents, public.rag_chunks to authenticated;
grant all privileges on public.organizations, public.organization_memberships,
    public.rag_documents, public.rag_chunks to service_role;

create policy "organization members can read their organization"
    on public.organizations for select to authenticated
    using (public.is_active_org_member(id));

create policy "users can read their own memberships"
    on public.organization_memberships for select to authenticated
    using (user_id = (select auth.uid()) and is_active = true);

create policy "organization members can read RAG documents"
    on public.rag_documents for select to authenticated
    using (public.is_active_org_member(organization_id));

create policy "organization members can read RAG chunks"
    on public.rag_chunks for select to authenticated
    using (public.is_active_org_member(organization_id));

-- The retrieval function is security-invoker by default, so RLS still applies
-- when a future browser client calls it using a user's Supabase JWT.
create or replace function public.match_rag_chunks(
    query_embedding extensions.vector(1536),
    target_organization_id uuid,
    target_deal_id uuid default null,
    only_verified_knowledge boolean default false,
    match_count integer default 6
)
returns table (
    document_id uuid,
    document_name text,
    deal_id uuid,
    source_type text,
    is_verified_knowledge boolean,
    page_number integer,
    chunk_index integer,
    content text,
    similarity double precision
)
language sql
stable
set search_path = public, extensions
as $$
    select
        chunk.document_id,
        document.document_name,
        chunk.deal_id,
        document.source_type,
        document.is_verified_knowledge,
        chunk.page_number,
        chunk.chunk_index,
        chunk.content,
        (1 - (chunk.embedding <=> query_embedding))::double precision as similarity
    from public.rag_chunks as chunk
    join public.rag_documents as document on document.id = chunk.document_id
    where chunk.organization_id = target_organization_id
      and document.organization_id = target_organization_id
      and document.is_archived = false
      and (target_deal_id is null or chunk.deal_id = target_deal_id)
      and (not only_verified_knowledge or document.is_verified_knowledge = true)
    order by chunk.embedding <=> query_embedding
    limit least(greatest(match_count, 1), 20);
$$;

revoke all on function public.match_rag_chunks(extensions.vector, uuid, uuid, boolean, integer) from public;
grant execute on function public.match_rag_chunks(extensions.vector, uuid, uuid, boolean, integer)
    to authenticated, service_role;

-- Raw PDFs use a private bucket. Object paths are always
-- {organization_id}/{document_id}/{filename}, allowing the policies below to
-- apply the same tenant boundary as the database records.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('h9n-deal-packages', 'h9n-deal-packages', false, 26214400, array['application/pdf'])
on conflict (id) do nothing;

create policy "organization members can read their private deal PDFs"
    on storage.objects for select to authenticated
    using (
        bucket_id = 'h9n-deal-packages'
        -- Look up the indexed document instead of casting a path segment. This
        -- is safe even if a malformed object name somehow reaches the bucket.
        and exists (
            select 1
            from public.rag_documents as document
            where document.storage_path = name
              and public.is_active_org_member(document.organization_id)
        )
    );
