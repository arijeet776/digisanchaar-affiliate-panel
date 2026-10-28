"""Part 21 - first Super Admin tool. Real module under test: tools/create_first_super_admin.provision.
Storage is an in-memory fake (LABELLED MOCK); the real storage adapters are not exercised here."""
import asyncio, sys
from pathlib import Path
from types import SimpleNamespace as NS
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import types
for n in ("app", "app.core"):
    sys.modules.setdefault(n, types.ModuleType(n)); sys.modules[n].__path__ = [str(ROOT / n.replace(".", "/"))]
from app.core.enums import AccountStatus, Role
from tools.create_first_super_admin import provision, ProvisionError, AUDIT_ACTION

res = []
def check(n, ok): res.append(bool(ok)); print(f"[{'PASS' if ok else 'FAIL'}] {n}")

class Col:
    def __init__(s): s.rows = []
    async def find_one(s, q): return next((r for r in s.rows if all(r.get(k) == v for k, v in q.items())), None)
    async def insert_one(s, d): d["_id"] = f"id{len(s.rows)+1}"; s.rows.append(d); return NS(inserted_id=d["_id"])
class DB(dict):
    def __missing__(s, k): s[k] = Col(); return s[k]

audit = []
async def aud(a, **kw): audit.append((a, kw))
H = lambda p: "HASH:" + p[::-1]
GOOD = "Str0ngPassword!"

async def main():
    db = DB()
    await db["users"].insert_one({"email": "superadmin", "role": "superadmin", "account_status": "active", "password_hash": "x"})
    before = [dict(r) for r in db["users"].rows]
    uid = await provision(db, " Admin@Example.com ", GOOD, H, aud)
    row = db["users"].rows[-1]
    check("C1 creates exactly one new user", len(db["users"].rows) == 2 and row["_id"] == uid)
    check("C2 role/status use real enums, email normalised, verified", row["role"] == Role.SUPER_ADMIN.value and row["account_status"] == AccountStatus.ACTIVE.value and row["email"] == "admin@example.com" and row["email_verified"] is True)
    check("C3 password stored only as hash, plaintext absent", row["password_hash"] == H(GOOD) and GOOD not in repr(row))
    check("C4 existing rows untouched (incl. invalid 'superadmin' row)", [dict(r) for r in db["users"].rows[:1]] == before)
    check("C5 audit entry written, contains no password", audit and audit[0][0] == AUDIT_ACTION and GOOD not in repr(audit))
    for name, args, kw in [("C6 refuses when an active super_admin exists", ("new@example.com", GOOD), {}),
                           ("C7 refuses duplicate email", ("admin@example.com", GOOD), {"allow_additional": True}),
                           ("C8 refuses weak password", ("w@example.com", "short"), {"allow_additional": True}),
                           ("C9 refuses malformed email", ("not-an-email", GOOD), {"allow_additional": True})]:
        n = len(db["users"].rows)
        try: await provision(db, *args, H, aud, **kw); ok = False
        except ProvisionError: ok = len(db["users"].rows) == n
        check(name, ok)
    uid2 = await provision(db, "second@example.com", GOOD, H, aud, allow_additional=True)
    check("C10 --allow-additional permits an explicit second admin", uid2 and len(db["users"].rows) == 3)
    print(f"{sum(res)}/{len(res)} passed"); return all(res)
sys.exit(0 if asyncio.run(main()) else 1)
