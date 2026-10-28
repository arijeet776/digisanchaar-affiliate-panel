# DigiSanchaar Cashflow — Production Deployment Runbook

Status of this document: **configuration/documentation only.** Nothing here has been
verified against live MongoDB, Supabase or a running container (see
`LAUNCH_CHECKLIST.md` for what still needs a real runtime).

## 1. Required environment variables (backend)

| Variable | Required in production | Notes |
|---|---|---|
| `ENVIRONMENT` | yes | `production` (docker-compose defaults to it) |
| `MONGO_URI` | yes, explicit | Atlas `mongodb+srv://…` string. App refuses to start if unset |
| `MONGO_DB_NAME` | yes, explicit | e.g. `digisnr_prod` |
| `POSTGRES_DSN` | yes, explicit | Supabase **Session pooler** string if the host is IPv4-only (copy from Supabase → Connect; do not guess the host) |
| `JWT_SECRET_KEY` | yes | ≥ 32 chars, random, not a placeholder (`openssl rand -hex 32`) |
| `ALLOWED_ORIGINS` (alias `CORS_ALLOWED_ORIGINS`) | yes | Comma-separated exact origins; `*` is rejected |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `JWT_ALGORITHM` | optional | defaults 30 / 14 / HS256 |
| `TRACKING_BASE_URL` | optional | bootstrap only; the value set in System Settings wins |
| `FORWARDED_ALLOW_IPS` | when behind a proxy | set by `docker-compose.yml` for the bundled nginx hop |

Frontend build arg: `VITE_API_BASE_URL` — leave empty for same-origin (`/api/v1` via nginx).

The backend fails at startup (before serving anything) if a production secret is missing,
too short, placeholder-like, or if CORS contains `*`.

## 2. Secret setup
- Create `backend/.env` from `backend/.env.example` **on the server only**, or inject the
  variables through your platform's secret manager. Never commit `.env`.
- Rotate any credential that has ever appeared in chat, tickets or a repository.
- Keep a copy of the secrets in your organization's password manager — the application
  cannot regenerate them (see `BACKUP_RECOVERY.md`).

## 3. MongoDB Atlas requirements
- A database user with `readWrite` on the application database only (least privilege —
  avoid `atlasAdmin` for the app).
- Network Access: add the **actual outbound IP/CIDR of the deployment host** (or use
  private connectivity). Never `0.0.0.0/0`.
- The application creates its collections and all indexes itself (`ensure_indexes`) on
  first successful connection; `/api/v1/health/ready` retries this until it succeeds and
  reports `mongo_indexes`.

## 4. Supabase / PostgreSQL requirements
- Postgres is the sole financial system of record (`financial_ledger`, `withdrawals`).
- Use the connection string from Supabase → Connect that matches your host's IP version
  (direct = IPv6, Session pooler = IPv4).
- The DB role needs DDL rights for the first start (to create tables/indexes), then may be
  reduced to DML-only on `financial_ledger`, `withdrawals`, `schema_migrations`.
- The ledger is append-only **by application convention**; the database does not forbid
  `UPDATE`/`DELETE`. Restrict the app role's privileges if you want database-level enforcement.

## 5. Migrations
- Files: `backend/migrations/*.sql`, applied in filename order, one transaction each,
  serialised by a Postgres advisory lock, recorded in `schema_migrations(filename)`.
- Every current migration uses `CREATE … IF NOT EXISTS`, so re-application is harmless.
- They run automatically at backend start when Postgres is reachable; otherwise
  `/health/ready` retries (30 s cool-down). A failed migration logs an `ERROR`, and
  readiness stays `503` with `"migrations": "failed"` — never silently healthy.
- Nothing in the application truncates, drops or resets data at startup.
- Before the first deploy against the existing Supabase project, check
  `select filename from schema_migrations` — the runner records `.sql` filenames; rows
  recorded under other names will simply cause the idempotent files to be re-applied.

## 6. Backend startup
```bash
cd <repo>
cp backend/.env.example backend/.env      # then fill in real values (server only)
docker compose build
docker compose up -d
docker compose logs -f backend            # look for "Connected to MongoDB", "Connected to PostgreSQL"
```
Container: non-root user, 2 uvicorn workers, `--proxy-headers`, healthcheck on `/api/v1/health/live`.

## 7. Frontend build
Built inside `frontend/Dockerfile` (`npm install` → `npm run build` → nginx). There is **no
`package-lock.json` in the repo**; commit one (`npm install` once, then commit) and switch the
Dockerfile to `npm ci` for reproducible builds.

## 8. nginx / reverse proxy
- Bundled nginx serves the SPA (history fallback) and proxies `/api/` to `backend:8000`.
- It **overwrites** `X-Forwarded-For` with the client address it sees. If you place another
  load balancer in front, change this deliberately (see comment in `frontend/nginx.conf`).
- Terminate TLS in front of nginx (cloud LB, Caddy, Traefik…); the bundled config listens on port 80 only.
- **Tracking domain:** short links are `https://<tracking-domain>/{campaign}/{link}`. Point that
  hostname **directly at the backend** (port 8000), not at the SPA nginx, or the SPA fallback
  will swallow the path. `/api/v1/t/{campaign}/{link}` works on the main host in the meantime.

## 9. Health checks
- `GET /api/v1/health/live` — process alive, no dependencies. Use for restart decisions.
- `GET /api/v1/health/ready` — 200 only when MongoDB is reachable and indexed, PostgreSQL is
  reachable, and migrations are applied; otherwise 503 with per-component `ok/error/pending/failed`.
  Responses contain no hostnames, DSNs or credentials.
- Frontend container: `GET /healthz`.

## 10. Smoke test (after deploy)
1. `curl -fsS https://<host>/api/v1/health/live` → `{"status":"alive"}`
2. `curl -fsS https://<host>/api/v1/health/ready` → `"status":"ready"`
3. Open the app; log in as the Super Admin; confirm the dashboard loads.
4. Confirm `/docs` returns 404 (disabled in production) and `/api/v1/auth/_dev/issue-token` returns 403.
5. Create a test campaign + link, click it, send a test postback, check the conversion appears.
6. Check `docker compose logs backend` for `ERROR` lines and for any secret/token material (there should be none).

## 11. Rollback
- **Application:** keep the previous image tag; `docker compose up -d` with the old tag. The app is
  stateless, so rollback is safe as long as the data schema is compatible.
- **Migrations:** the SQL migrations are additive (`CREATE … IF NOT EXISTS`) and have no down
  scripts. Rolling the app back does **not** undo them; old code ignores the extra objects.
- **Data:** a database rollback means a point-in-time restore through the provider
  (see `BACKUP_RECOVERY.md`). Restoring Postgres without restoring MongoDB (or the reverse)
  can desynchronise ledger entries from conversions — restore both to the same timestamp.

## 12. Post-deployment verification
Work through `LAUNCH_CHECKLIST.md` and record the result and date for each item.

## Known operational limits
- Rate limiting is **in-process memory** (per worker, per replica); with 2 workers × N replicas the
  effective limit is higher and resets on restart. Use a shared limiter at the edge if that matters.
- Outbound postbacks/webhooks are delivered by the application process; there is no external queue.
- The `Custom` postback adapter remains fail-closed: specification insufficient (`CUSTOM_POSTBACK_SPEC_GAP.md`).
