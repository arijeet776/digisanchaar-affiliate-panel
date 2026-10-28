# DigiSanchaar Affiliate Panel

Affiliate / performance-marketing platform: Super Admin, Manager and Publisher panels, tracking links, postbacks,
conversion review, wallet and withdrawals.

| Part | Stack | Host |
|---|---|---|
| `frontend/` | React + Vite + TypeScript | Netlify (or any static host) |
| `backend/` | FastAPI | Render (Root Directory `backend`) |
| Database | Supabase (PostgreSQL) over HTTPS | Supabase |

## Deploy (new client)
1. **Supabase**: create a project, then run in SQL Editor, in this order:
   `backend/migrations/supabase/001_schema.sql`, then `002_campaign_purge.sql`.
2. **Render** (Web Service, Root Directory `backend`): build `pip install -r requirements.txt`,
   start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Environment:
   `ENVIRONMENT=production`, `STORAGE_BACKEND=supabase_rest`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (secret key),
   `JWT_SECRET_KEY` (32+ random chars), `ALLOWED_ORIGINS` (exact frontend origin), `BRAND_NAME`, `FORWARDED_ALLOW_IPS=*`.
3. **Netlify**: base directory `frontend`, build `npm run build`, publish `dist`,
   env `VITE_API_BASE_URL=https://<your-render-service>.onrender.com/api/v1`.
4. **First Super Admin**: `python backend/tools/create_first_super_admin.py` (see the file header) or
   `backend/tools/create_super_admin.sql`.

More: `docs/DEPLOYMENT_RUNBOOK.md`, `docs/LAUNCH_CHECKLIST.md`, `docs/SUPABASE_REST_BACKEND.md`, `docs/BACKUP_RECOVERY.md`.

## Click ids
Every click gets a unique id starting with `DGSNR` (e.g. `DGSNR4F8K2P9QXA`). It is stored as `digisnr_click_id`
and travels to the advertiser in the campaign's click-id parameter (and optional extra parameters).
