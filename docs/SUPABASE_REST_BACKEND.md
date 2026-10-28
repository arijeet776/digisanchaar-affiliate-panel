# Supabase (PostgreSQL) backend over HTTPS — `STORAGE_BACKEND=supabase_rest`

No TCP driver (no pg/asyncpg/mongoose): only HTTPS to
`{SUPABASE_URL}/rest/v1/rpc/qx_exec` (PostgREST) with httpx.

## How it works
* `migrations/supabase/001_schema.sql` (generated from `app/storage/schema.py`, 27 tables) creates every table,
  unique constraint and index, the `qx_exec` storage engine, and locks everything down.
* `app/storage/supabase_adapter.py` sends ONE request per storage operation; `qx_exec` runs it as ONE transaction.
  Withdrawals/ledger use `batch` (atomic) with a per-publisher advisory lock; the ledger is append-only (trigger).
* All repositories/services/frontend are unchanged (Motor-compatible facade over the adapter).
* Regenerate SQL after any schema change: `cd backend && python -m tools.generate_supabase_sql` (`--check` in CI).

## Keys — important
* The **publishable key cannot be used by the backend**. With RLS on (and no policies) it can read/write nothing — that is the
  protection: leaking it exposes no data. The backend needs the **secret / service_role key**.
* Put it only in Render → Environment as `SUPABASE_SERVICE_KEY`. Never in chat, git, Netlify or any `VITE_*` variable.
  The app refuses to start if a publishable/anon key is configured.

## Setup (once)
1. Supabase → SQL Editor → paste `migrations/supabase/001_schema.sql` → Run. (Safe to re-run.)
   Success check: `select count(*) from public.qx_tables;` → 27.
2. Render env: `STORAGE_BACKEND=supabase_rest`, `SUPABASE_URL=https://<ref>.supabase.co`, `SUPABASE_SERVICE_KEY=<secret key>`.
   `MONGO_*` and `POSTGRES_DSN` are not needed in this mode. Keep `ALLOWED_ORIGINS`, `JWT_SECRET_KEY`, `ENVIRONMENT`.
3. Create the first Super Admin (not a public route): `cd backend && python -m tools.create_first_super_admin --email <you>`.
4. Check `/api/v1/health/ready`, then the `Server-Timing` response header (`storage;dur=..;desc="N calls"`).
5. Speed: create the Supabase project in the **same region** as the Render service; network round trip, not the database, dominates.

## Verified vs not
Verified offline on a real PostgreSQL 16 (local): migration applies and re-applies, 77 application scenarios, 22 concurrency/atomicity/
injection/lock-down checks. NOT verified: the real Supabase project, PostgREST/HTTPS path, the new `sb_secret_` key header handling,
real latency, Render connectivity.

## First Super Admin (no Python needed)
Run `backend/tools/create_super_admin.sql` in the Supabase SQL Editor after replacing `<ADMIN_EMAIL>` and `<STRONG_PASSWORD>` there
(typed only in the editor; hashed in-database with bcrypt; refuses weak passwords, an existing email, or a second active admin).
Alternative: `python -m tools.create_first_super_admin --email <email>` (prompts for the password, never echoes it).
Login: the normal `/login` page with that email + password; role `super_admin` lands on `/dashboard`. There is no separate admin URL and no credential in the frontend.
