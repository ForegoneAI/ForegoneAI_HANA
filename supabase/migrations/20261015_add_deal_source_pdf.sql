-- H9N Milestone 2.3: keep each deal's uploaded PDF, so a reviewer can open it
-- at the page a value was cited from.
--
-- The PDF goes in the existing private bucket (h9n-deal-packages) at
-- {organization_id}/{deal_id}/source.pdf. Signed-in users get no direct
-- access to it: the API checks the deal belongs to one of their
-- organizations and returns a short-lived signed URL. The bucket's existing
-- read policy only covers indexed RAG documents, so it doesn't apply here.
--
-- Depends on 20261014_create_h9n_deals.sql.

alter table public.deals add column if not exists source_storage_path text unique;

-- A deal's PDF must be stored under its own organization's folder.
alter table public.deals drop constraint if exists deals_source_storage_path_in_organization;
alter table public.deals add constraint deals_source_storage_path_in_organization
    check (source_storage_path is null or source_storage_path like organization_id::text || '/%');
