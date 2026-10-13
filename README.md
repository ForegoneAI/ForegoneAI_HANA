# H9N Milestone 4 — First-Pass Underwriting

Implements M4.1 finance calculations, M4.2 input provenance and append-only Supabase snapshots, M4.3 scenario engine, and M4.4 React underwriting panel.

## Integration into existing H9N repo
1. Copy `backend/app/h9n/underwriting/` into your repo's same path; copy `backend/tests/test_underwriting.py`.
2. Apply `supabase/migrations/20261013_create_underwriting_runs.sql` after existing organization/auth migrations.
3. In `backend/app/main.py` add:

   ```python
   from backend.app.h9n.underwriting.api import router as underwriting_router
   app.include_router(underwriting_router)
   ```
4. Copy `frontend/components/UnderwritingPanel.tsx` into the existing web app (adapt path to actual frontend layout) and render it inside the approved deal workspace with `dealId`, Supabase access `token`, and optional `apiBase`.
5. Install dependencies already used by H9N: `fastapi`, `pydantic>=2`, `supabase`, `pytest`.
6. Run `python -m pytest backend/tests/test_underwriting.py -q`.

## IMPORTANT: integration/security items before merging
- `POST /calculate` is a stateless preview and currently accepts arbitrary inputs for a signed-in user; for private deal data, bind deal_id to the authenticated tenant and use the saved approved profile as the authoritative source of facts. Do not trust client-submitted `source_fact` or `evidence_id` values. Enforce this server-side before pilot deployment.
- `POST /save` checks organization ownership and approved review status via current local DealStore. Move this check to the eventual Supabase deal table when M2.4 migration lands. It currently persists user-provided inputs; source-fact reconciliation against the approved Deal Profile is required before production use.
- The UI starts with blank inputs intentionally; connect approved Deal Profile fields and evidence IDs using the actual current schema. Do not overwrite the source profile.
- The SQL table is append-only by application convention; for stricter immutability revoke UPDATE/DELETE from service workflows or use DB triggers/role-specific policies.
- `deal_id` is text because the current DealStore uses string IDs. Align with the future canonical deal schema.
- Real finance conventions need domain review: annualized NOI, debt service timing, exit NOI convention, interest-only vs amortizing balance, treatment of capex, tax, fees, refinance, and equity contributions. This is a simple unlevered-property/levered-equity first pass, not investment advice or an audited underwriting model.
- Default scenarios are examples, not sourced assumptions. Record approval and provenance for user overrides.
- Frontend is a functional starter, not a finished production design. Add input validation, evidence click-through, error/loading polish and design-system styling.
