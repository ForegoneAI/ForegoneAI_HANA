# H9N RAG pipeline

This is a source-cited retrieval layer for future H9N institutional memory. It indexes private deal documents and approved knowledge, then returns matching passages with their document and page number. It deliberately does **not** generate an investment answer or replace the approved Deal Profile.

## Before running it

1. Create a Supabase project.
2. Apply [`supabase/migrations/20260921_create_h9n_rag.sql`](../supabase/migrations/20260921_create_h9n_rag.sql) in the Supabase SQL Editor or with the Supabase CLI.
3. Copy `.env.example` to `.env` if it does not already exist, then set real values for `OPENROUTER_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `H9N_RAG_INTERNAL_API_KEY`.
4. Activate the local environment and start the API:

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --reload
```

The default route uses OpenRouter's `openai/text-embedding-3-small` with 1,536 dimensions. If you change the embedding model or dimension in `.env`, create a matching migration and re-embed the corpus; a vector column cannot mix dimensions.

## API

All RAG endpoints require the internal-only `X-H9N-API-Key` header. This is a safe development gate, **not customer authentication**. Before exposing these endpoints to customers, replace it with Supabase JWT validation and derive `organization_id` from the authenticated membership rather than accepting it from the request body.

### Ingest page-preserved text

```bash
curl -X POST http://localhost:8000/api/h9n/rag/documents/text \
  -H "Content-Type: application/json" \
  -H "X-H9N-API-Key: $H9N_RAG_INTERNAL_API_KEY" \
  -d '{
    "organization_id": "11111111-1111-1111-1111-111111111111",
    "document_name": "investment-criteria.md",
    "source_type": "investment_criteria",
    "is_verified_knowledge": true,
    "pages": [{"page_number": 1, "text": "Target cap rate is at least 6.0%."}]
  }'
```

### Ingest a private PDF

```bash
curl -X POST http://localhost:8000/api/h9n/rag/documents/pdf \
  -H "X-H9N-API-Key: $H9N_RAG_INTERNAL_API_KEY" \
  -F "organization_id=11111111-1111-1111-1111-111111111111" \
  -F "source_type=deal_package" \
  -F "file=@deal-package.pdf;type=application/pdf"
```

Text-based PDFs are stored in the private Supabase bucket and chunked without crossing a page boundary. Scanned/image-only PDFs need OCR before indexing.

### Retrieve source passages

```bash
curl -X POST http://localhost:8000/api/h9n/rag/search \
  -H "Content-Type: application/json" \
  -H "X-H9N-API-Key: $H9N_RAG_INTERNAL_API_KEY" \
  -d '{
    "organization_id": "11111111-1111-1111-1111-111111111111",
    "query": "What evidence supports the stated cap rate?",
    "verified_knowledge_only": false
  }'
```

The search response contains passages, similarity scores, source category, document name, and page number. A later answer-generation endpoint must use these citations and label any model-written synthesis as analysis rather than source fact.

## File layout

```text
backend/app/h9n/rag/
  api.py            guarded FastAPI endpoints
  config.py         .env configuration and validation
  pdf_ingestion.py  bounded, text-based PDF extraction
  chunking.py       page-preserving deterministic chunking
  embeddings.py     OpenRouter embedding provider (via the OpenAI-compatible SDK)
  repository.py     Supabase Storage/Postgres adapter
  service.py        ingestion and retrieval orchestration
  schemas.py        validated API contracts
supabase/migrations/
  20260921_create_h9n_rag.sql  tables, vector index, RLS, private bucket
```

## Safety controls already included

- PDFs must have both a `.pdf` filename, `application/pdf` content type, and PDF signature.
- PDFs are limited to 25 MB and 1,000 pages; encrypted and textless PDFs are rejected.
- Source PDFs go to a private bucket; vectors retain document/page provenance.
- The database schema includes `organization_id` on every document and chunk, RLS policies, and a tenant-filtered search RPC.
- The server-only Supabase service-role key and OpenRouter key remain in `.env`, which Git ignores.
- The RAG API only retrieves passages. It never returns an uncited LLM decision or investment recommendation.
