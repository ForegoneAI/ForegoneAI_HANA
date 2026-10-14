# HANA web app (H9N)

The signed-in app where a reviewer uploads a deal package and works on its Deal Profile. Next.js (App Router) + React + TypeScript. It talks to the FastAPI backend in `backend/` and uses Supabase only to sign in.

This is separate from `site/`, the public marketing site, which is plain HTML published as-is to foregone.ai. Nothing in this folder is published by that workflow.

## Pages

| Path | What it does |
|---|---|
| `/login` | Email and password sign-in through Supabase Auth |
| `/deals` | Every deal your organization has saved, newest first, to reopen one. `/` redirects here |
| `/deals/new` | Upload a PDF and follow it through uploading → extracting → ready (M2.1). A member of several organizations first chooses which one the deal is for (M2.5) |
| `/deals/[id]` | The deal workspace (M2.2): the Deal Profile as an editable form grouped by property, transaction, operations, financing, sponsor and assumptions. Each field is marked cited, missing, uncertain, conflicting, unverified (a proposed value to accept or dismiss) or corrected. Save, mark reviewed, approve, reopen or reject with feedback (M2.4), and see the deal's history |

Pages other than `/login` send visitors who aren't signed in to `/login`, then back. That redirect is for convenience. The real protection is the API itself, which rejects any request without a valid session token (M2.5).

## Running it locally

1. Start the backend from the repo root (see `backend/README.md`):

   ```bash
   source .venv/bin/activate
   uvicorn backend.app.main:app --reload
   ```

   The backend allows calls from `http://localhost:3000` by default (`H9N_ALLOWED_ORIGINS` in the root `.env`).

2. Configure the app:

   ```bash
   cd frontend
   cp .env.example .env.local
   ```

   Fill in the Supabase project URL and its **publishable** key (Project Settings → API Keys). Never use the service-role key here: everything in `NEXT_PUBLIC_*` ends up in the browser.

3. Install and run:

   ```bash
   npm install
   npm run dev
   ```

   Open http://localhost:3000 and sign in with a Supabase user that belongs to an organization ("Signing in" in `backend/README.md` explains how to set one up).

## Checks

```bash
npm run lint   # ESLint
npm test       # unit and component tests (Vitest; component tests run in jsdom)
npm run build  # production build, including the TypeScript check
```

GitHub runs all three on every pull request that touches `frontend/` (`.github/workflows/frontend-ci.yml`).

## Code layout

- `src/app/`: pages (one folder per route)
- `src/components/`: `RequireSignIn` (the sign-in gate), `AppHeader`, and the shared building blocks later pages reuse: `Button`/`ButtonLink`, `Notice` (errors are announced to screen readers), `Badge` (review status, field flags). Colours and spacing live once, as tokens at the top of `src/app/globals.css`
- `src/lib/api.ts`: calls to the H9N API, adding the session token and turning API errors into plain messages
- `src/lib/supabase.ts`: the browser Supabase client
- `src/lib/upload.ts`: checks a chosen file before uploading (PDF, 50 MB limit)
- `src/lib/organizations.ts`: which organization an upload is for, and whether the user must choose one
- `src/components/review/`: the deal workspace's review form (`DealReviewForm`, one `FieldRow` per field), `ReviewActions` and `DealHistoryPanel`
- `src/lib/dealFields.ts`: every Deal Profile field, its group and kind (money, percent, ...), and how typed values are read and shown
- `src/lib/fieldStatus.ts`: how far each field can be trusted, worked out from the extractor's flag lists. When M1.2 adds a structured status per field, only this file needs to change
- `src/lib/reviewForm.ts`: turns a reviewer's edits into the exact changes to save
- `src/lib/history.ts`: a deal's history as a readable timeline
- `src/lib/deals.ts`: how a deal's title, review status and save time read in the app
