# Backup & Recovery — responsibilities and limits

**Nothing in this repository creates, schedules or verifies backups.** Everything below is
what the operator must confirm; no backup has been verified by the authors.

| Asset | Where it lives | Backup responsibility | Verified? |
|---|---|---|---|
| Operational data (users, campaigns, clicks, conversions, tickets, audit logs, sessions) | MongoDB Atlas | Atlas backup / continuous (PITR) availability depends on the cluster tier — the project cluster is a **free-tier** cluster, which does not include continuous cloud backup. Confirm the tier and enable a backup plan, or schedule `mongodump`. | **NOT VERIFIED** |
| Financial ledger & withdrawals | Supabase PostgreSQL | Supabase daily backups / PITR depend on the plan. Confirm in Supabase → Database → Backups. | **NOT VERIFIED** |
| Application code | Git repository + built images | Keep tagged releases and the previous image. | n/a |
| Secrets (`MONGO_URI`, `POSTGRES_DSN`, `JWT_SECRET_KEY`) | Platform secret store | Store in the org password manager. Losing `JWT_SECRET_KEY` only logs everyone out; losing DB credentials is recoverable by resetting them in Atlas/Supabase. | **NOT VERIFIED** |

## Restore principles
1. **Restore MongoDB and PostgreSQL to the same point in time.** Conversions (Mongo) and the
   financial ledger (Postgres) reference each other by `conversion_id`; restoring one alone
   creates orphans or missing earnings.
2. After restoring Postgres, the app's idempotency keys (`earning:{conversion_id}`,
   `reversal:{conversion_id}`, withdrawal hold/release keys) make replays safe: re-confirming a
   conversion does not create a second earning.
3. Do not run the test suites against a restored or production database — `part9_financial_test.py`
   executes `TRUNCATE`. Use a throwaway local Postgres only.

## Migration recovery
- Migrations are forward-only. If one fails, readiness reports `"migrations": "failed"` and the
  log has an `ERROR`; fix the cause (connectivity, privileges) and restart or wait for the
  30-second readiness retry. A failed migration is rolled back (own transaction); earlier ones stay applied.
- To roll back a schema change, restore from backup or write a new forward migration. There are no down scripts.

## Deployment / application rollback
See `DEPLOYMENT_RUNBOOK.md` §11.

## Credential rotation
Rotate the Atlas user password and Supabase database password after any exposure, update the
secret store, redeploy, and confirm `/api/v1/health/ready` is `ready`.
**A database password was exposed earlier in this project's history; rotation was reported by the
owner but has not been independently verified.**
