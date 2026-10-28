"""Part 23 - Supabase SQL engine: concurrency, atomicity, injection and lock-down, on REAL PostgreSQL 16.
Needs QX_PG="host:port:user:dbname" (default /tmp:54329:postgres:qx) with the migration applied. psql only, no drivers."""
import json, os, subprocess, sys, threading
host, port, user, db = os.environ.get("QX_PG", "/tmp:54329:postgres:qx").split(":")
res = []
def check(n, ok, d=""):
    res.append(bool(ok)); print(f"[{'PASS' if ok else 'FAIL'}] {n}" + (f" - {d}" if d and not ok else ""))
def sql(q, role=None):
    pre = f"set role {role}; " if role else ""
    o = subprocess.run(["psql", "-h", host, "-p", port, "-U", user, "-d", db, "-At", "-q"], input=pre + q, capture_output=True, text=True)
    return (o.stdout.strip(), o.stderr.strip())
def ex(req, role=None):
    out, err = sql("select public.qx_exec($q$" + json.dumps(req) + "$q$::jsonb);", role)
    return json.loads(out.splitlines()[-1]) if out else {"_err": err}

sql("truncate users, withdrawals restart identity; alter table financial_ledger disable trigger trg_financial_ledger_append_only; truncate financial_ledger restart identity; alter table financial_ledger enable trigger trg_financial_ledger_append_only;")
led = lambda i, amt, typ="earning", d="credit": {"op": "create", "table": "financial_ledger", "data": {"ledger_id": f"L{i}", "idempotency_key": f"k{i}", "transaction_type": typ, "direction": d, "publisher_id": "P1", "amount": amt, "currency": "INR", "status": "posted", "source": "t", "created_at": "2026-10-01T00:00:00.000Z", "effective_at": "2026-10-01T00:00:00.000Z"}}
check("S1 fund wallet 100.00", ex({"action": "batch", "operations": [led(1, "100.00")]})["success"])

# --- concurrency: 6 simultaneous withdrawals of 40.00 against a 100.00 wallet => at most 2 succeed ---
outs = [None] * 6
def worker(i):
    ops = [{"op": "guard", "type": "balance_gte", "publisher_id": "P1", "amount": "40.00"},
           {"op": "create", "table": "withdrawals", "as": "w", "data": {"withdrawal_id": f"W{i}", "idempotency_key": f"wi{i}", "publisher_id": "P1", "amount": "40.00", "currency": "INR", "status": "requested", "requested_at": "2026-10-02T00:00:00.000Z", "updated_at": "2026-10-02T00:00:00.000Z"}},
           {"op": "create", "table": "financial_ledger", "data": {**led(100 + i, "40.00", "withdrawal_hold", "debit")["data"], "withdrawal_id": f"W{i}"}}]
    outs[i] = ex({"action": "batch", "operations": ops})
ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
[t.start() for t in ts]; [t.join() for t in ts]
okc = sum(1 for o in outs if o["success"])
bal = ex({"action": "ledger_summary", "filters": {"publisher_id": "P1"}})["data"]
check("S2 6 parallel 40.00 withdrawals vs 100.00 balance: exactly 2 accepted (advisory lock)", okc == 2, str(okc))
check("S3 balance never negative: 100 - 80 = 20.00", float(bal["total_credits"]) - float(bal["total_debits"]) == 20.0, str(bal))
check("S4 rejected ones were INSUFFICIENT_BALANCE", all(o["success"] or o["error"]["code"] == "INSUFFICIENT_BALANCE" for o in outs))
check("S5 failed batches left no orphan withdrawal rows", sql("select count(*) from withdrawals")[0] == "2")

# --- atomic rollback: 2nd op violates unique -> 1st op undone ---
before = sql("select count(*) from withdrawals")[0]
r = ex({"action": "batch", "operations": [
    {"op": "create", "table": "withdrawals", "data": {"withdrawal_id": "WX1", "idempotency_key": "wx1", "publisher_id": "P2", "amount": "5.00"}},
    {"op": "create", "table": "withdrawals", "data": {"withdrawal_id": "WX1", "idempotency_key": "wx2", "publisher_id": "P2", "amount": "5.00"}}]})
check("S6 duplicate key inside a batch -> DUPLICATE_KEY", r.get("error", {}).get("code") == "DUPLICATE_KEY")
check("S7 ...and the whole batch rolled back", sql("select count(*) from withdrawals")[0] == before)

# --- compare-and-set: parallel approvals, exactly one wins ---
sql("insert into withdrawals (withdrawal_id, idempotency_key, publisher_id, amount, status) values ('WCAS','kc','P3',10,'requested');")
wins = []
def appr(i):
    r = ex({"action": "find_one_and_update", "table": "withdrawals", "filters": {"withdrawal_id": "WCAS", "status": {"$in": ["requested"]}}, "update": {"$set": {"status": "approved", "reviewed_by": f"u{i}"}}, "return_document": "after"})
    wins.append(r["data"] is not None)
ts = [threading.Thread(target=appr, args=(i,)) for i in range(5)]
[t.start() for t in ts]; [t.join() for t in ts]
check("S8 5 parallel approvals of the same withdrawal: exactly one succeeds", sum(wins) == 1, str(wins))

# --- ledger is append-only (engine + trigger) ---
check("S9 engine refuses ledger update", ex({"action": "update", "table": "financial_ledger", "id": "L1", "update": {"$set": {"amount": "1.00"}}})["error"]["code"] == "FORBIDDEN_TABLE_OPERATION")
o, e = sql("update financial_ledger set amount = 1; ")
check("S10 trigger blocks raw UPDATE even for superuser", "append-only" in e)
o, e = sql("delete from financial_ledger;")
check("S11 trigger blocks raw DELETE", "append-only" in e)

# --- injection / validation ---
inj = ex({"action": "query", "table": "users", "filters": {"email": "x' or '1'='1"}})
check("S12 quote in a value is just data (0 rows, no error)", inj["success"] and inj["pagination"]["total"] == 0)
check("S13 malicious field name rejected", ex({"action": "query", "table": "users", "filters": {"email; drop table users; --": 1}})["error"]["code"] == "VALIDATION_ERROR")
check("S14 unknown table rejected", ex({"action": "count", "table": "pg_catalog.pg_user"})["error"]["code"] == "INVALID_TABLE")
check("S15 unknown operator rejected", ex({"action": "query", "table": "users", "filters": {"email": {"$where": "1"}}})["error"]["code"] == "VALIDATION_ERROR")
check("S16 users table still exists", sql("select to_regclass('public.users')")[0] == "users")

# --- lock-down: anon / authenticated can reach nothing; service_role can ---
for role in ("anon", "authenticated"):
    o, e = sql("select count(*) from users;", role)
    check(f"S17 {role} cannot SELECT users (the publishable key path)", "permission denied" in e, e[:80])
    o, e = sql("select public.qx_exec('{\"action\":\"ping\"}'::jsonb);", role)
    check(f"S18 {role} cannot call qx_exec", "permission denied" in e, e[:80])
check("S19 service_role can call qx_exec", ex({"action": "ping"}, "service_role").get("success") is True)
check("S20 RLS enabled on every table", sql("select count(*) from pg_tables where schemaname='public' and not rowsecurity")[0] == "0")
print(f"{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
