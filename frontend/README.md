# HANA web app (H9N)

The signed-in app where a reviewer uploads a deal package and works on its Deal Profile. Next.js (App Router) + React + TypeScript. It talks to the FastAPI backend in `backend/` and uses Supabase only to sign in.

This is separate from `site/`, the public marketing site, which is plain HTML published as-is to foregone.ai. Nothing in this folder is published by that workflow.

## Pages

| Path | What it does |
|---|---|
| `/login` | Email and password sign-in through Supabase Auth |
| `/deals/new` | Upload a PDF and follow it through uploading → extracting → ready (M2.1) |
| `/deals/[id]` | The deal workspace. Shows the key extracted values for now; the review form (M2.2) replaces it |

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
npm test       # unit tests (Vitest)
npm run build  # production build, including the TypeScript check
```

GitHub runs all three on every pull request that touches `frontend/` (`.github/workflows/frontend-ci.yml`).

## Code layout

- `src/app/`: pages (one folder per route)
- `src/components/`: `RequireSignIn` (the sign-in gate) and `AppHeader`
- `src/lib/api.ts`: calls to the H9N API, adding the session token and turning API errors into plain messages
- `src/lib/supabase.ts`: the browser Supabase client
- `src/lib/upload.ts`: checks a chosen file before uploading (PDF, 50 MB limit)
