"""
Part 16.2.1 — dual publisher invite flow, approve & assign, idempotency,
tamper resistance and profile data continuity.

Runs the REAL services/repositories (invite_service, onboarding_service,
invite/manager/publisher repositories, email_service) against an in-memory
fake of the Mongo collections, with third-party packages stubbed. It does NOT
exercise FastAPI routing/RBAC dependencies or a real MongoDB — those need the
real environment (see docs).
    python3 tests/part16_2_1_invite_flow_test.py
"""
import asyncio
import itertools
import os
import sys
import types
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ---------------- stubs for third-party packages ----------------
def mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class PyMongoError(Exception): pass
class DuplicateKeyError(PyMongoError): pass
class InvalidId(Exception): pass


class ObjectId:
    _c = itertools.count(1)
    def __init__(self, v=None):
        self.v = str(v) if v is not None else f"{next(ObjectId._c):024x}"
    def __str__(self): return self.v
    def __eq__(self, o): return isinstance(o, ObjectId) and o.v == self.v
    def __hash__(self): return hash(self.v)
    def __repr__(self): return f"ObjectId({self.v})"


mod("pymongo"); mod("pymongo.errors", DuplicateKeyError=DuplicateKeyError, PyMongoError=PyMongoError)
mod("bson", ObjectId=ObjectId); mod("bson.errors", InvalidId=InvalidId)
mod("fastapi", Request=object, status=types.SimpleNamespace(
    HTTP_400_BAD_REQUEST=400, HTTP_404_NOT_FOUND=404, HTTP_409_CONFLICT=409, HTTP_401_UNAUTHORIZED=401,
    HTTP_403_FORBIDDEN=403, HTTP_503_SERVICE_UNAVAILABLE=503, HTTP_422_UNPROCESSABLE_ENTITY=422,
    HTTP_429_TOO_MANY_REQUESTS=429))
mod("fastapi.responses", JSONResponse=object)

# ---------------- in-memory Mongo ----------------
def _match(doc, flt):
    for k, v in flt.items():
        dv = doc.get(k)
        if isinstance(v, dict):
            for op, ov in v.items():
                if op == "$gt":
                    a = dv.replace(tzinfo=None) if hasattr(dv, "tzinfo") else dv
                    b = ov.replace(tzinfo=None) if hasattr(ov, "tzinfo") else ov
                    if not (a > b): return False
                else:
                    raise NotImplementedError(op)
        elif dv != v:
            return False
    return True


class Cursor:
    def __init__(self, docs): self.docs = docs
    def __aiter__(self):
        async def gen():
            for d in self.docs: yield d
        return gen()
    async def to_list(self, length=None): return list(self.docs)


class Coll:
    def __init__(self, unique=()):
        self.docs, self.unique = [], unique
    async def insert_one(self, doc):
        for u in self.unique:
            if any(d.get(u) == doc.get(u) for d in self.docs):
                raise DuplicateKeyError(u)
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return types.SimpleNamespace(inserted_id=doc["_id"])
    async def find_one(self, flt):
        return next((d for d in self.docs if _match(d, flt)), None)
    def find(self, flt=None):
        return Cursor([d for d in self.docs if _match(d, flt or {})])
    async def find_one_and_update(self, flt, upd, return_document=False, upsert=False):
        d = await self.find_one(flt)
        if d is None: return None
        before = dict(d)
        d.update(upd.get("$set", {}))
        return d if return_document else before
    async def update_one(self, flt, upd):
        d = await self.find_one(flt)
        if d is None: return types.SimpleNamespace(modified_count=0)
        d.update(upd.get("$set", {}))
        return types.SimpleNamespace(modified_count=1)


class DB(dict):
    def __missing__(self, k):
        self[k] = Coll(unique=("email",) if k == "users" else ("publisher_id",) if k == "publishers" else ("manager_id",) if k == "managers" else ())
        return self[k]

DB_INSTANCE = DB()
mod("app"); mod("app.db"); mod("app.core"); mod("app.services")
mod("app.db.mongodb", get_database=lambda: DB_INSTANCE)
audit_log, otp_sent = [], []


async def audit_record(action, **kw): audit_log.append((action, kw))
async def send_otp(*a, **k): otp_sent.append(a)

_tok = itertools.count(1)
mod("app.core.security", generate_secure_token=lambda: f"tok{next(_tok)}", hash_token=lambda t: "h:" + t,
    hash_password=lambda p: "hashed:" + p[::-1])
mod("app.db.audit_repository", record=audit_record)
mod("app.services.otp_service", send_otp=send_otp)

import importlib.util
def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m

load("app.core.enums", "app/core/enums.py"); load("app.core.exceptions", "app/core/exceptions.py")
load("app.core.audit_actions", "app/core/audit_actions.py"); load("app.core.email_utils", "app/core/email_utils.py")
manager_repository = load("app.db.manager_repository", "app/db/manager_repository.py")
publisher_repository = load("app.db.publisher_repository", "app/db/publisher_repository.py")
invite_repository = load("app.db.invite_repository", "app/db/invite_repository.py")
for n, m in [("manager_repository", manager_repository), ("publisher_repository", publisher_repository), ("invite_repository", invite_repository)]:
    setattr(sys.modules["app.db"], n, m)
email_service = load("app.services.email_service", "app/services/email_service.py")
sys.modules["app.services"].email_service = email_service
emails = []
class Capture(email_service.EmailBackend):
    async def send(self, message): emails.append(message)
email_service._backend = Capture()
invite_service = load("app.services.invite_service", "app/services/invite_service.py")
onboarding = load("app.services.onboarding_service", "app/services/onboarding_service.py")
from app.core.enums import Role, AccountStatus
from app.core.exceptions import ForbiddenError, ValidationAppError, UnauthorizedError, ConflictError

# pydantic schema check (real file) — extra="forbid" on publisher signup
try:
    import pydantic
    pydantic.EmailStr = str  # email-validator not installable here; irrelevant to extra=forbid
    sys.path.insert(0, ROOT)
    schema_src = open(os.path.join(ROOT, "app/schemas/onboarding.py")).read()
    mod("app.schemas"); mod("app.schemas.auth", _validate_password_strength=lambda v: v, validate_publisher_password=lambda v: v)
    schemas = load("app.schemas.onboarding", "app/schemas/onboarding.py")
except Exception as e:  # pragma: no cover
    schemas = None; print("schema import skipped:", e)

PW = "Str0ngP@ssw0rd!x"


async def mk_user(email, role, status="active"):
    r = await DB_INSTANCE["users"].insert_one({"email": email, "role": role, "account_status": status, "password_hash": "x",
                                               "created_at": datetime.now(timezone.utc)})
    return str(r.inserted_id)


async def mk_manager(email, name, status="active"):
    uid = await mk_user(email, "manager", status)
    prof = await manager_repository.create_manager_profile(uid, name)
    return uid, prof["manager_id"]


async def user_status(uid):
    return (await DB_INSTANCE["users"].find_one({"_id": ObjectId(uid)}))["account_status"]


async def main():
    sa = await mk_user("sa@x.com", "super_admin")
    m1_uid, m1 = await mk_manager("m1@x.com", "Manager One")
    m2_uid, m2 = await mk_manager("m2@x.com", "Manager Two")
    _, m_susp = await mk_manager("ms@x.com", "Suspended Mgr", "suspended")
    _, m_pend = await mk_manager("mp@x.com", "Pending Mgr", "pending")

    # --- assignable managers: active only
    act = {m["manager_id"] for m in await manager_repository.list_active_managers()}
    check("E0 assignable list = ACTIVE managers only", act == {m1, m2}, str(act))

    # ---------- TEST A: manager invite ----------
    tok, inv = await invite_service.create_publisher_invite(Role.MANAGER, m1_uid, None, "AM99999-ignored")
    check("A1 manager invite bound to the manager's OWN id (body manager_id ignored)", inv["manager_id"] == m1)
    check("A2 invitation_type = MANAGER_INVITE", inv["invitation_type"] == "MANAGER_INVITE")
    emails.clear()
    u = await onboarding.signup_publisher(tok, "Pub.A@X.com", PW, "Pub A", mobile="9876543210", company="Acme")
    prof = await publisher_repository.get_publisher_by_user_id(str(u["_id"]))
    check("A3 application PENDING", u["account_status"] == "pending")
    check("A4 manager relationship stored from invite", prof["manager_id"] == m1)
    check("A5 provenance stored (type/invited_by/invite_id)", prof["invitation_type"] == "MANAGER_INVITE" and prof["invited_by"] == m1_uid and prof["invite_id"])
    check("A6 mobile/company/name persisted on authoritative record", (prof["mobile"], prof["company"], prof["display_name"]) == ("9876543210", "Acme", "Pub A"))
    check("A7 password stored hashed only", u["password_hash"].startswith("hashed:") and PW not in str(u))
    check("A8 manager visible to its manager", prof in await publisher_repository.list_publishers_by_manager(m1))
    check("A9 NOT visible to other manager", prof not in await publisher_repository.list_publishers_by_manager(m2))
    to = sorted(e.to for e in emails)
    check("A10 notified assigned manager + super admin (once each)", to == ["m1@x.com", "sa@x.com"], str(to))
    check("A11 submission audited", any(a == "PUBLISHER_APPLICATION_SUBMITTED" for a, _ in audit_log))

    # ---------- TEST C: manager approves ----------
    emails.clear()
    pid = str(u["_id"])
    await onboarding.approve_publisher(pid, Role.MANAGER, m1_uid)
    check("C1 manager approval -> ACTIVE", await user_status(pid) == "active")
    check("C2 manager relationship retained", (await publisher_repository.get_publisher_by_user_id(pid))["manager_id"] == m1)
    # ---------- TEST H: duplicate approval ----------
    n_users = len(DB_INSTANCE["users"].docs); n_pubs = len(DB_INSTANCE["publishers"].docs)
    for actor in [(Role.SUPER_ADMIN, sa), (Role.MANAGER, m1_uid)]:
        try:
            await onboarding.approve_publisher(pid, *actor); ok = False
        except onboarding.AlreadyProcessedError: ok = True
        check(f"H1 second approval by {actor[0].value} -> ALREADY_PROCESSED", ok)
    check("H2 no duplicate user/publisher records", (len(DB_INSTANCE['users'].docs), len(DB_INSTANCE['publishers'].docs)) == (n_users, n_pubs))
    check("H3 exactly one approval email", sum(1 for e in emails if "approved" in e.subject) == 1, str(len(emails)))

    # ---------- TEST B: SA approves manager-invited ----------
    tok, _ = await invite_service.create_publisher_invite(Role.MANAGER, m2_uid, None, None)
    u2 = await onboarding.signup_publisher(tok, "b@x.com", PW, "Pub B", "9999999999", "B Co")
    await onboarding.approve_publisher(str(u2["_id"]), Role.SUPER_ADMIN, sa)
    p2 = await publisher_repository.get_publisher_by_user_id(str(u2["_id"]))
    check("B1 SA approves manager-invited w/o dropdown -> ACTIVE, manager kept", await user_status(str(u2["_id"])) == "active" and p2["manager_id"] == m2)
    try:
        await onboarding.approve_publisher(str(u2["_id"]), Role.SUPER_ADMIN, sa, assign_manager_id=m1); ok = False
    except Exception: ok = True
    check("B2 approval cannot be used to silently reassign an assigned publisher", ok)

    # ---------- TEST D: SA invite ----------
    emails.clear()
    tok, inv = await invite_service.create_publisher_invite(Role.SUPER_ADMIN, sa, None, None)
    check("D1 SA invite has NO manager id", inv["manager_id"] is None and inv["invitation_type"] == "SUPER_ADMIN_INVITE")
    u3 = await onboarding.signup_publisher(tok, "d@x.com", PW, "Pub D", "8888888888", "D Co")
    p3 = await publisher_repository.get_publisher_by_user_id(str(u3["_id"]))
    d_id = str(u3["_id"])
    check("D2 PENDING with manager_id = None", u3["account_status"] == "pending" and p3["manager_id"] is None)
    lists = [await publisher_repository.list_publishers_by_manager(m) for m in (m1, m2)]
    check("D3 in no manager's list", all(p3 not in l for l in lists))
    check("D4 only super admin notified (no manager email)", sorted(e.to for e in emails) == ["sa@x.com"], str([e.to for e in emails]))

    # manager can't act on unassigned
    for fn, args in [(onboarding.approve_publisher, (d_id, Role.MANAGER, m1_uid)), (onboarding.reject_publisher, (d_id, Role.MANAGER, m1_uid, None))]:
        try:
            await fn(*args); ok = False
        except ForbiddenError: ok = True
        check(f"D5 manager cannot {fn.__name__.split('_')[0]} an unassigned publisher", ok)

    # ---------- TEST E: approve & assign ----------
    # Part 17: choosing a Manager at approval is OPTIONAL (see part17_test.py)
    for bad, why in [(m_susp, "suspended manager"), (m_pend, "pending manager"), ("AM00000", "unknown manager")]:
        try:
            await onboarding.approve_publisher(d_id, Role.SUPER_ADMIN, sa, assign_manager_id=bad); ok = False
        except ValidationAppError: ok = True
        check(f"E1 approve refused: {why}", ok)
    check("E2 still PENDING & unassigned after refusals", await user_status(d_id) == "pending" and (await publisher_repository.get_publisher_by_user_id(d_id))["manager_id"] is None)
    emails.clear()
    await onboarding.approve_publisher(d_id, Role.SUPER_ADMIN, sa, assign_manager_id=m2)
    p3 = await publisher_repository.get_publisher_by_user_id(d_id)
    check("E3 Approve & Assign -> ACTIVE with selected manager", await user_status(d_id) == "active" and p3["manager_id"] == m2)
    check("E4 now visible under selected manager only", p3 in await publisher_repository.list_publishers_by_manager(m2) and p3 not in await publisher_repository.list_publishers_by_manager(m1))
    check("E5 assignment audited", any(a == "PUBLISHER_MANAGER_ASSIGNED" for a, _ in audit_log))
    check("E6 assigned manager + publisher emailed once", sorted(e.to for e in emails) == ["d@x.com", "m2@x.com"], str([e.to for e in emails]))
    try:
        await onboarding.approve_publisher(d_id, Role.SUPER_ADMIN, sa, assign_manager_id=m2); ok = False
    except onboarding.AlreadyProcessedError: ok = True
    check("E7 duplicate approve&assign idempotent (no extra effect)", ok and len(emails) == 2)

    # ---------- TEST F: reject ----------
    tok, _ = await invite_service.create_publisher_invite(Role.SUPER_ADMIN, sa, None, None)
    u4 = await onboarding.signup_publisher(tok, "f@x.com", PW, "Pub F", "7777777777", "F Co")
    await onboarding.reject_publisher(str(u4["_id"]), Role.SUPER_ADMIN, sa, "not a fit")
    p4 = await publisher_repository.get_publisher_by_user_id(str(u4["_id"]))
    check("F1 rejected, no manager assigned, record retained", await user_status(str(u4["_id"])) == "rejected" and p4["manager_id"] is None)
    try:
        await onboarding.approve_publisher(str(u4["_id"]), Role.SUPER_ADMIN, sa, assign_manager_id=m1); ok = False
    except onboarding.AlreadyProcessedError: ok = True
    p4 = await publisher_repository.get_publisher_by_user_id(str(u4["_id"]))
    check("F2 approving a rejected application fails AND rolls back the assignment", ok and p4["manager_id"] is None and await user_status(str(u4["_id"])) == "rejected")

    # ---------- TEST G: tampering ----------
    tok, _ = await invite_service.create_publisher_invite(Role.SUPER_ADMIN, sa, None, None)
    if schemas:
        try:
            schemas.PublisherSignupRequest(invite_token=tok, email="g@x.com", password=PW, display_name="G", manager_id=m1); ok = False
        except Exception: ok = True
        check("G1 signup payload carrying manager_id is refused (extra=forbid)", ok)
    u5 = await onboarding.signup_publisher(tok, "g@x.com", PW, "Pub G", "6666666666", "G Co")
    p5 = await publisher_repository.get_publisher_by_user_id(str(u5["_id"]))
    check("G2 URL/manager id cannot influence assignment: SA-invite stays unassigned", p5["manager_id"] is None)
    # manager suspended after issuing invite
    mt_uid, mt = await mk_manager("mt@x.com", "Temp Mgr")
    tok, _ = await invite_service.create_publisher_invite(Role.MANAGER, mt_uid, None, None)
    await DB_INSTANCE["users"].find_one_and_update({"_id": ObjectId(mt_uid)}, {"$set": {"account_status": "suspended"}})
    try:
        await onboarding.signup_publisher(tok, "h@x.com", PW, "Pub H", "5555555555", "H Co"); ok = False
    except ConflictError: ok = True
    check("G3 invite from a now-suspended manager is refused at signup", ok)
    check("G4 refused signup created no account", await DB_INSTANCE["users"].find_one({"email": "h@x.com"}) is None)
    # SA with an inactive manager_id
    try:
        await invite_service.create_publisher_invite(Role.SUPER_ADMIN, sa, None, m_susp); ok = False
    except Exception: ok = True
    check("G5 SA cannot bind an invite to an inactive manager", ok)
    # token reuse + wrong email
    tok, _ = await invite_service.create_publisher_invite(Role.SUPER_ADMIN, sa, "only@x.com", None)
    try:
        await onboarding.signup_publisher(tok, "other@x.com", PW, "O", "5555555", "O"); ok = False
    except UnauthorizedError: ok = True
    check("G6 email-bound invite refuses a different email", ok)

    # ---------- TEST I: profile continuity ----------
    prof = await publisher_repository.get_publisher_by_user_id(d_id)
    acct = await DB_INSTANCE["users"].find_one({"_id": ObjectId(d_id)})
    mgr = await manager_repository.get_manager_by_manager_id(prof["manager_id"])
    view = {"display_name": prof["display_name"], "email": acct["email"], "mobile": prof["mobile"], "company": prof["company"],
            "publisher_id": prof["publisher_id"], "status": acct["account_status"], "member_since": prof["created_at"], "manager": mgr["display_name"]}
    check("I1 profile has name/email/mobile/company/id/status/since/manager", all(view.values()) and view["manager"] == "Manager Two", str({k: v for k, v in view.items() if k != 'member_since'}))
    check("I2 publisher id is random 4-digit, not sequential", len(prof["publisher_id"]) == 4 and prof["publisher_id"].isdigit())
    check("I3 no plaintext password anywhere on the records", PW not in str(acct) + str(prof))
    check("I4 no invite secret in audit log", not any("tok" in str(kw.get("metadata", {})).replace("invitation_type", "") and "tok1" in str(kw) for _, kw in audit_log))


asyncio.run(main())
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
