# Release, Hosting and Connection Check

## Topology
- **Frontend**: static Vite/React build → Netlify (`netlify.toml`, SPA fallback, security headers). Needs only `VITE_API_BASE_URL` (public) = `https://<backend-host>/api/v1`.
- **Backend**: FastAPI container (`backend/Dockerfile`) on a separate host (Render, Fly.io, Railway, a VPS, Cloud Run…). **Netlify does not host it.** Netlify Functions are not a substitute.
- **Storage**: `STORAGE_BACKEND=supabase_rest` (Supabase over HTTPS, recommended) or `mongodb_supabase`. Only the backend talks to the database.

## Secrets (backend private environment only)
`SUPABASE_SERVICE_KEY`, `JWT_SECRET_KEY`, other secrets as in `backend/.env.example`. Put them in the host's secret manager. Never in `VITE_*` variables, the repo or the ZIP. If a real secret was ever committed or pasted somewhere public, rotate it.

## Backend variables to set on the host
`ENVIRONMENT=production`, `STORAGE_BACKEND=supabase_rest`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ALLOWED_ORIGINS=https://<your-netlify-site>` (exact origin, no `*`), `FORWARDED_ALLOW_IPS=<proxy>`, plus the other production values in `backend/.env.example`. Auth uses bearer tokens (no cookies), so cross-origin CORS is enough.

## Verify the backend connection
Open `https://<backend-host>/api/v1/health/ready` - it must answer `ready` with `storage_backend: supabase_rest`.

## Netlify steps (manual, as no Netlify connector was available)
1. Connect the repo (or drag-drop the built `frontend/dist`); `netlify.toml` supplies base/command/publish/redirects.
2. Site settings → Environment variables → `VITE_API_BASE_URL=https://<backend-host>/api/v1`.
3. Deploy a **preview** first; promote to production only after the backend is live and `ALLOWED_ORIGINS` includes the site origin.
4. A `package-lock.json` is not in the repo: run `npm install` once, commit the lockfile, then change the build command to `npm ci`.

## Registration & approval (no email OTP)
- Signup creates a `PENDING` account (Users tab) and sends no email. Only a Super Admin approves it (Publishers / Managers pages); open-registration publishers can be approved by a Super Admin only.
- Login: PENDING -> "Your account is pending Super Admin approval."; REJECTED -> "Your account registration has been rejected." No token or session is issued, and every request re-checks the account status in storage.
- Existing accounts are never auto-activated. Accounts that were PENDING stay PENDING and appear in the approval lists; `email_verified` is no longer used for any decision.
- Password reset still uses an email code; it needs an email provider (not implemented) or a Super Admin-assisted reset.
- Every API response carries `Server-Timing` (total ms; storage ms and number of storage calls) for latency measurement.
