# Launch Checklist

Legend: **DONE (static)** = confirmed by reading the repository only.
**PENDING — REQUIRES EMERGENT RUNTIME** = cannot be claimed until run against a real environment.
Nothing is marked PASS on the basis that code exists.

| # | Item | Status |
|---|---|---|
| 1 | Production secrets configured (MONGO_URI, MONGO_DB_NAME, POSTGRES_DSN, JWT_SECRET_KEY, ALLOWED_ORIGINS) | PENDING — REQUIRES EMERGENT RUNTIME (app refuses to start without them: DONE static) |
| 2 | MongoDB Atlas reachable from the deployment host (IP allowlist = real egress IP, not 0.0.0.0/0) | PENDING — REQUIRES EMERGENT RUNTIME |
| 3 | PostgreSQL/Supabase reachable (correct pooler/direct string for host IP version) | PENDING — REQUIRES EMERGENT RUNTIME |
| 4 | Migrations applied (`schema_migrations` lists all `backend/migrations/*.sql`) | PENDING — REQUIRES EMERGENT RUNTIME |
| 5 | MongoDB indexes initialised (`/health/ready` → `mongo_indexes: ok`) | PENDING — REQUIRES EMERGENT RUNTIME |
| 6 | Backend container starts, non-root, healthcheck green | PENDING — REQUIRES EMERGENT RUNTIME |
| 7 | `/health/live` 200 and `/health/ready` 200 | PENDING — REQUIRES EMERGENT RUNTIME |
| 8 | Frontend builds (`npm install && npm run build`, `tsc --noEmit`, lint) | PENDING — REQUIRES EMERGENT RUNTIME |
| 9 | Frontend reaches backend through nginx (`/api/v1/...`) | PENDING — REQUIRES EMERGENT RUNTIME |
| 10 | Authentication works (login, refresh, logout, revoked session → 401) | PENDING — REQUIRES EMERGENT RUNTIME (tests: part2, part13) |
| 11 | RBAC / IDOR verified (admin vs manager vs publisher scoping) | PENDING — REQUIRES EMERGENT RUNTIME (tests: part3, 4, 7, 14) |
| 12 | Tracking works (link → click → DigiSanchaar click id → redirect) | PENDING — REQUIRES EMERGENT RUNTIME (part5) |
| 13 | Conversion / postback works incl. duplicate handling | PENDING — REQUIRES EMERGENT RUNTIME (part6, part14) |
| 14 | Financial flows verified (earning, hold, withdrawal, reversal) on a **throwaway** Postgres | PENDING — REQUIRES EMERGENT RUNTIME (part9) |
| 15 | Webhooks verified (signature, delivery log, replay) | PENDING — REQUIRES EMERGENT RUNTIME (part10, part14) |
| 16 | Support / security operations verified | PENDING — REQUIRES EMERGENT RUNTIME (part11) |
| 17 | Logs checked: no passwords/JWTs/API keys/DSNs | PENDING — REQUIRES EMERGENT RUNTIME (static scan of log calls: DONE) |
| 18 | No secrets exposed (repo scan, image layers, health output) | Repo scan DONE (static); image-layer check PENDING |
| 19 | `/docs`, `/redoc` disabled and `_dev/*` endpoints 403 in production | PENDING — REQUIRES EMERGENT RUNTIME (code gating: DONE static) |
| 20 | Tracking domain points at the backend (not the SPA nginx) | PENDING — REQUIRES EMERGENT RUNTIME |
| 21 | Backup/recovery responsibility confirmed for Atlas and Supabase | PENDING — operator action (see BACKUP_RECOVERY.md) |
| 22 | Database credentials rotated after earlier exposure | PENDING — operator confirmation |
| 23 | `package-lock.json` committed; Dockerfile switched to `npm ci` | PENDING — needs a machine with npm registry access |
