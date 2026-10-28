"""
Part 17 — open registration, optional-manager approval, later assignment,
WhatsApp setting validation, publisher macro vocabulary/engine, postback config
precedence, publisher-safe report rows, export jobs and password policy.

Runs the REAL services/repositories (invite_service, onboarding_service,
invite/manager/publisher repositories, email_service) against an in-memory
fake of the Mongo collections, with third-party packages stubbed. It does NOT
exercise FastAPI routing/RBAC dependencies or a real MongoDB — those need the
real environment (see docs).
    python3 tests/part17_test.py
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
def _cmp(a, b):
    a = a.replace(tzinfo=None) if hasattr(a, "tzinfo") else a
    b = b.replace(tzinfo=None) if hasattr(b, "tzinfo") else b
    return a, b


def _match(doc, flt):
    for k, v in flt.items():
        dv = doc.get(k)
        if isinstance(v, dict):
            for op, ov in v.items():
                if op == "$in":
                    if dv not in ov: return False
                elif op in ("$gt", "$gte", "$lt", "$lte"):
                    if dv is None: return False
                    a, b = _cmp(dv, ov)
                    if not {"$gt": a > b, "$gte": a >= b, "$lt": a < b, "$lte": a <= b}[op]: return False
                else:
                    raise NotImplementedError(op)
        elif dv != v:
            return False
    return True


class Cursor:
    def __init__(self, docs): self.docs = list(docs)
    def sort(self, key, direction=None):
        keys = key if isinstance(key, list) else [(key, direction)]
        for k, d in reversed(keys):
            self.docs.sort(key=lambda x: (x.get(k) is None, x.get(k)), reverse=(d == -1))
        return self
    def limit(self, n): self.docs = self.docs[:n]; return self
    def __aiter__(self):
        async def gen():
            for d in self.docs: yield d
        return gen()
    async def to_list(self, length=None): return list(self.docs)


def _proj(d, proj):
    if not proj: return d
    return {k: v for k, v in d.items() if k not in [p for p, x in proj.items() if x == 0]}


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
    async def find_one(self, flt, sort=None):
        docs = [d for d in self.docs if _match(d, flt)]
        if sort:
            docs = Cursor(docs).sort(sort).docs
        return docs[0] if docs else None
    def find(self, flt=None, proj=None):
        return Cursor([_proj(d, proj) for d in self.docs if _match(d, flt or {})])
    async def count_documents(self, flt): return len([d for d in self.docs if _match(d, flt)])
    async def find_one_and_update(self, flt, upd, return_document=False, upsert=False):
        d = await self.find_one(flt)
        if d is None: return None
        before = dict(d)
        d.update(upd.get("$set", {}))
        return d if return_document else before
    async def update_one(self, flt, upd):
        d = await self.find_one(flt)
        if d is None: return types.SimpleNamespace(modified_count=0, matched_count=0)
        d.update(upd.get("$set", {}))
        return types.SimpleNamespace(modified_count=1, matched_count=1)


class DB(dict):
    def __missing__(self, k):
        self[k] = Coll(unique=("email",) if k == "users" else ("publisher_id",) if k == "publishers" else ("manager_id",) if k == "managers" else ())
        return self[k]

DB_INSTANCE = DB()
mod("app"); mod("app.db"); mod("app.core"); mod("app.services"); mod("app.schemas")
mod("app.db.mongodb", get_database=lambda: DB_INSTANCE)
audit_log, otp_sent = [], []


async def audit_record(action, **kw): audit_log.append((action, kw))
async def send_otp(*a, **k): otp_sent.append(a)

_tok = itertools.count(1)
mod("app.core.security", generate_secure_token=lambda: f"tok{next(_tok)}", hash_token=lambda t: "h:" + t,
    hash_password=lambda p: "hashed:" + p[::-1])
mod("app.db.audit_repository", record=audit_record)
mod("app.services.otp_service", send_otp=send_otp)
mod("app.config", get_settings=lambda: types.SimpleNamespace())

import importlib.util
def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m

load("app.core.enums", "app/core/enums.py"); load("app.core.exceptions", "app/core/exceptions.py")
load("app.core.audit_actions", "app/core/audit_actions.py"); load("app.core.email_utils", "app/core/email_utils.py")
manager_repository = load("app.db.manager_repository", "app/db/manager_repository.py")
publisher_repository = load("app.db.publisher_repository", "app/db/publisher_repository.py")
invite_repository = load("app.db.invite_repository", "app/db/invite_repository.py")
settings_repository = load("app.db.settings_repository", "app/db/settings_repository.py")
conversion_repository = load("app.db.conversion_repository", "app/db/conversion_repository.py")
for n, m in [("manager_repository", manager_repository), ("publisher_repository", publisher_repository),
             ("invite_repository", invite_repository), ("settings_repository", settings_repository),
             ("conversion_repository", conversion_repository)]:
    setattr(sys.modules["app.db"], n, m)
async def _list_links(publisher_id=None, **k): return [{"campaign_id": "C1", "publisher_id": publisher_id}]
async def _get_campaign(cid): return {"summary": {"name": "Camp One"}}
setattr(sys.modules["app.db"], "tracking_repository", types.SimpleNamespace(list_links=_list_links))
setattr(sys.modules["app.db"], "campaign_repository", types.SimpleNamespace(get_campaign=_get_campaign))
mod("app.services.postback_adapters", ADAPTERS={})
sys.modules["app.services"].postback_adapters = sys.modules["app.services.postback_adapters"]
email_service = load("app.services.email_service", "app/services/email_service.py")
sys.modules["app.services"].email_service = email_service
emails = []
class Capture(email_service.EmailBackend):
    async def send(self, message): emails.append(message)
email_service._backend = Capture()
invite_service = load("app.services.invite_service", "app/services/invite_service.py")
onboarding = load("app.services.onboarding_service", "app/services/onboarding_service.py")
macro_engine = load("app.services.macro_engine", "app/services/macro_engine.py")
settings_service = load("app.services.settings_service", "app/services/settings_service.py")
postback_service = load("app.services.postback_service", "app/services/postback_service.py")
report = load("app.services.publisher_report_service", "app/services/publisher_report_service.py")
from app.core.enums import Role, AccountStatus
from app.core.exceptions import ForbiddenError, ValidationAppError, ConflictError, NotFoundError
from app.core import audit_actions

import pydantic
pydantic.EmailStr = str  # email-validator not installable here
auth_schema = load("app.schemas.auth", "app/schemas/auth.py")
schemas = load("app.schemas.onboarding", "app/schemas/onboarding.py")

PW = "Abcde1!xyz"


async def mk_user(email, role, status="active"):
    r = await DB_INSTANCE["users"].insert_one({"email": email, "role": role, "account_status": status, "password_hash": "x",
                                               "created_at": datetime.now(timezone.utc)})
    return str(r.inserted_id)


async def mk_manager(email, name, status="active", mobile=None):
    uid = await mk_user(email, "manager", status)
    prof = await manager_repository.create_manager_profile(uid, name, mobile)
    return uid, prof["manager_id"]


async def status_of(uid):
    return (await DB_INSTANCE["users"].find_one({"_id": ObjectId(uid)}))["account_status"]


async def raises(exc, coro):
    try:
        await coro
    except exc:
        return True
    except Exception as e:  # wrong type
        print("   unexpected:", type(e).__name__, e)
        return False
    return False


async def _lm(m):
    r = publisher_repository.list_publishers_by_manager(m)
    if hasattr(r, "__aiter__"):
        return [x async for x in r]
    return await r


async def main():
    # ===== 1. password policy =====
    r = auth_schema.password_rule_results
    ok_pw = ["Abcde1!", "Hello1@World", "ZZZZZ9#"]
    bad = {"Abcd1!": "only 4 letters", "abcde1!": "no uppercase", "Abcdef!": "no number", "Abcde12": "no special", "": "empty"}
    check("P1 valid passwords accepted", all(auth_schema.validate_publisher_password(x) == x for x in ok_pw))
    for pw, why in bad.items():
        check(f"P2 rejected: {why}", await raises(ValueError, _wrap(auth_schema.validate_publisher_password, pw)))
    check("P3 rule results expose 4 independent flags", len(r("Abcde1!")) == 4 and all(v if isinstance(v, bool) else v.get("met") for v in (r("Abcde1!").values() if isinstance(r("Abcde1!"), dict) else [x["met"] if isinstance(x, dict) else x for x in r("Abcde1!")])))
    check("P4 128-char cap", await raises(ValueError, _wrap(auth_schema.validate_publisher_password, "Abcde1!" + "a" * 130)))
    try:
        schemas.PublisherSignupRequest(email="a@b.com", password="weak", display_name="Ab", mobile="9", company="C"); ok = False
    except Exception: ok = True
    check("P5 backend schema rejects weak password independently of the UI", ok)
    req = schemas.PublisherSignupRequest(email="a@b.com", password=PW, display_name="Ab", mobile="9876543210", company="C")
    check("P6 signup schema valid with NO invite token", req.invite_token is None)
    try:
        schemas.PublisherSignupRequest(email="a@b.com", password=PW, display_name="Ab", manager_id="AM10001"); ok = False
    except Exception: ok = True
    check("P7 signup schema refuses manager_id (extra=forbid)", ok)

    # ===== 2. open registration =====
    sa = await mk_user("sa@x.com", "super_admin")
    m1_uid, m1 = await mk_manager("m1@x.com", "Manager One", mobile="9000000001")
    m2_uid, m2 = await mk_manager("m2@x.com", "Manager Two")
    _, m_susp = await mk_manager("ms@x.com", "Suspended", "suspended")
    emails.clear()
    u = await onboarding.signup_publisher(None, "Open.Pub@X.com", PW, "Open Pub", mobile="9876543210", company="Open Co")
    uid = str(u["_id"])
    prof = await publisher_repository.get_publisher_by_user_id(uid)
    check("R1 open signup -> PENDING", u["account_status"] == "pending")
    check("R2 manager_id None; source OPEN_REGISTRATION", prof["manager_id"] is None and prof.get("invitation_type") == "OPEN_REGISTRATION", str({k: prof.get(k) for k in ('manager_id', 'invitation_type')}))
    check("R3 mobile/company/name persisted", (prof["mobile"], prof["company"], prof["display_name"]) == ("9876543210", "Open Co", "Open Pub"))
    check("R4 password hashed, never stored plain", u["password_hash"].startswith("hashed:") and PW not in str(u) + str(prof))
    check("R5 no invite consumed/created", len(DB_INSTANCE["invites"].docs) == 0 and not prof.get("invite_id"))
    check("R6 application audited without password", any(a == "PUBLISHER_APPLICATION_SUBMITTED" for a, _ in audit_log) and PW not in str(audit_log))
    check("R7 only super admin notified (no manager yet)", sorted(e.to for e in emails) == ["sa@x.com"], str([e.to for e in emails]))
    check("R8 visible to no manager", prof not in await _lm(m1) and prof not in await _lm(m2))
    check("R9 open signup requires mobile", await raises(ValidationAppError, onboarding.signup_publisher(None, "n1@x.com", PW, "No Mobile", None, "Co")))
    check("R10 open signup requires company", await raises(ValidationAppError, onboarding.signup_publisher(None, "n2@x.com", PW, "No Co", "9876543210", None)))
    check("R11 failed signups create no account", await DB_INSTANCE["users"].find_one({"email": "n1@x.com"}) is None and await DB_INSTANCE["users"].find_one({"email": "n2@x.com"}) is None)
    check("R12 duplicate email refused", await raises(Exception, onboarding.signup_publisher(None, "open.pub@x.com", PW, "Dup", "9876543210", "Co")))

    # ===== 3. approval without a manager =====
    check("A1 manager role cannot approve an unassigned publisher", await raises(ForbiddenError, onboarding.approve_publisher(uid, Role.MANAGER, m1_uid)))
    check("A2 manager role cannot assign during approval", await raises(ForbiddenError, onboarding.approve_publisher(uid, Role.MANAGER, m1_uid, assign_manager_id=m1)))
    check("A3 still pending after refusals", await status_of(uid) == "pending")
    emails.clear(); audit_log.clear()
    await onboarding.approve_publisher(uid, Role.SUPER_ADMIN, sa)
    prof = await publisher_repository.get_publisher_by_user_id(uid)
    check("A4 approve with NO manager -> ACTIVE, manager_id null", await status_of(uid) == "active" and prof["manager_id"] is None)
    check("A5 approval audited; no assignment audited", [a for a, _ in audit_log] == ["PUBLISHER_APPROVED"], str([a for a, _ in audit_log]))
    check("A6 approval email sent once", [e.to for e in emails] == ["open.pub@x.com"])
    check("A7 second approval idempotent (ALREADY_PROCESSED, no side effects)", await raises(onboarding.AlreadyProcessedError, onboarding.approve_publisher(uid, Role.SUPER_ADMIN, sa)) and len(emails) == 1)

    # ===== 4. later assignment / reassignment =====
    emails.clear(); audit_log.clear()
    await onboarding.assign_manager(uid, m1, sa)
    prof = await publisher_repository.get_publisher_by_user_id(uid)
    check("L1 later assign -> manager set, status unchanged", prof["manager_id"] == m1 and await status_of(uid) == "active")
    check("L2 audit PUBLISHER_MANAGER_ASSIGNED", [a for a, _ in audit_log] == ["PUBLISHER_MANAGER_ASSIGNED"])
    check("L3 manager notified once", [e.to for e in emails] == ["m1@x.com"])
    check("L4 now in manager's list only", prof in await _lm(m1) and prof not in await _lm(m2))
    emails.clear(); audit_log.clear()
    await onboarding.assign_manager(uid, m1, sa)
    check("L5 same manager = no-op (no audit, no email)", not audit_log and not emails)
    await onboarding.assign_manager(uid, m2, sa)
    prof = await publisher_repository.get_publisher_by_user_id(uid)
    check("L6 reassignment works + audit PUBLISHER_MANAGER_REASSIGNED", prof["manager_id"] == m2 and [a for a, _ in audit_log] == ["PUBLISHER_MANAGER_REASSIGNED"])
    check("L7 reassign to suspended manager refused", await raises(ValidationAppError, onboarding.assign_manager(uid, m_susp, sa)))
    check("L8 reassign to unknown manager refused", await raises(ValidationAppError, onboarding.assign_manager(uid, "AM00000", sa)))
    check("L9 unknown publisher -> not found", await raises(NotFoundError, onboarding.assign_manager(str(ObjectId()), m1, sa)))

    # approve + assign, and rejected flow
    u2 = await onboarding.signup_publisher(None, "two@x.com", PW, "Pub Two", "9111111111", "Two Co"); id2 = str(u2["_id"])
    check("M1 approve+assign to suspended manager refused", await raises(ValidationAppError, onboarding.approve_publisher(id2, Role.SUPER_ADMIN, sa, assign_manager_id=m_susp)))
    check("M2 still pending/unassigned after refusal", await status_of(id2) == "pending" and (await publisher_repository.get_publisher_by_user_id(id2))["manager_id"] is None)
    await onboarding.approve_publisher(id2, Role.SUPER_ADMIN, sa, assign_manager_id=m1)
    check("M3 approve+assign -> ACTIVE with that manager", await status_of(id2) == "active" and (await publisher_repository.get_publisher_by_user_id(id2))["manager_id"] == m1)
    u3 = await onboarding.signup_publisher(None, "three@x.com", PW, "Pub Three", "9222222222", "Three Co"); id3 = str(u3["_id"])
    await onboarding.reject_publisher(id3, Role.SUPER_ADMIN, sa, "no")
    check("M4 rejected: record retained, status rejected", await status_of(id3) == "rejected" and await publisher_repository.get_publisher_by_user_id(id3) is not None)
    check("M5 rejected cannot be approved", await raises(onboarding.AlreadyProcessedError, onboarding.approve_publisher(id3, Role.SUPER_ADMIN, sa)))
    check("M6 rejected cannot be assigned a manager", await raises(ConflictError, onboarding.assign_manager(id3, m1, sa)))
    check("M7 rejection audited", any(a == "PUBLISHER_REJECTED" for a, _ in audit_log))

    # manager mobile
    mgr = await manager_repository.get_manager_by_manager_id(m1)
    check("G1 manager mobile persisted at creation", mgr.get("mobile") == "9000000001")
    await manager_repository.set_manager_mobile(m1_uid, "9555555555")
    check("G2 manager mobile updatable", (await manager_repository.get_manager_by_manager_id(m1)).get("mobile") == "9555555555")
    check("G3 signup_manager accepts mobile", "mobile" in onboarding.signup_manager.__code__.co_varnames)

    # ===== 5. WhatsApp link validation =====
    v = settings_service.validate_whatsapp_link
    check("W1 valid group link accepted", v("https://chat.whatsapp.com/AbC123") == "https://chat.whatsapp.com/AbC123")
    check("W2 wa.me accepted", v("https://wa.me/919876543210").startswith("https://wa.me/"))
    check("W3 empty clears", v("") == "" and v(None) == "" and v("   ") == "")
    for bad_url, why in [("http://chat.whatsapp.com/x", "http"), ("https://evil.example.com/x", "other host"),
                         ("https://chat.whatsapp.com.evil.com/x", "suffix spoof"), ("javascript:alert(1)", "js scheme"),
                         ("https://user:pw@chat.whatsapp.com/x", "credentials"), ("https://chat.whatsapp.com/" + "a" * 400, "too long")]:
        check(f"W4 rejected: {why}", await raises(ValidationAppError, _wrap(v, bad_url)))

    # ===== 6. publisher macro vocabulary =====
    tokens = [m["token"] for m in macro_engine.PUBLISHER_MACROS]
    want = {"click_id", "campaign_id", "campaign_name", "publisher_id", "event", "status", "date", "date_time", "ip", "country",
            "country_code", "state", "city", "payout"} | {f"p{i}" for i in range(1, 11)}
    check("X1 publisher vocabulary is exactly the specified set", set(tokens) == want, str(set(tokens) ^ want))
    check("X2 no UTM / sub-id / revenue exposed", not any(t.startswith(("utm", "sub", "f_sub")) or t in ("revenue", "margin", "original_rate") for t in tokens))
    check("X3 no duplicate tokens", len(tokens) == len(set(tokens)))
    check("X4 PUBLISHER_MACRO_KEYS matches", set(macro_engine.PUBLISHER_MACRO_KEYS) == want)
    check("X5 every token is engine-approved", set(tokens) <= macro_engine.APPROVED_MACROS)
    out, used = macro_engine.substitute_macros("https://t.example/pb?c={click_id}&e={event}&p={p3}&x={unknown}", {"click_id": "QX 1&", "event": "Install"})
    check("X6 values URL-encoded, missing => blank, unknown untouched", out == "https://t.example/pb?c=QX%201%26&e=Install&p=&x={unknown}", out)
    out, _ = macro_engine.substitute_macros("{p1}", {"p1": "a" * 500})
    check("X7 value capped at 200 chars", len(out) == 200)
    check("X8 macros are plain substitutions (no evaluation)", macro_engine.substitute_macros("{click_id}", {"click_id": "{event}"})[0] == "%7Bevent%7D")

    # ===== 7. postback url validation + masking =====
    vo = postback_service.validate_outbound_url
    check("U1 valid template accepted", vo("https://t.example/pb?c={click_id}&p={payout}&a={p10}").startswith("https://"))
    for tmpl, why in [("https://t.example/?s={utm_source}", "utm_source"), ("https://t.example/?s={nonsense}", "unknown macro"),
                      ("https://t.example/?r={revenue}", "revenue"), ("ftp://t.example/", "scheme"),
                      ("http://localhost/x", "localhost"), ("http://127.0.0.1/x", "loopback"), ("http://10.0.0.5/x", "private ip"),
                      ("https://u:p@t.example/", "credentials"), ("", "empty")]:
        check(f"U2 rejected: {why}", await raises(ValidationAppError, _wrap(vo, tmpl)))
    sm = postback_service.safe_url("https://t.example/pb?click=1&token=SECRET123&api_key=abc&n=2")
    check("U3 secret-looking params masked in logs", "SECRET123" not in sm and "abc" not in sm and "click=1" in sm and "n=2" in sm, sm)

    # ===== 8. build_outbound_values: publisher-safe =====
    conv = {"digisnr_click_id": "QX1", "campaign_id": "C1", "publisher_id": "4821", "event": "KYC", "status": "approved",
            "payout": 10.0, "revenue": 99.0, "original_rate": 50, "margin": 40, "conversion_created_at": datetime(2026, 10, 5, 12, 30, tzinfo=timezone.utc)}
    click = {"ip": "1.2.3.4", "country": "IN", "original_params": {"p1": "a", "p7": "g", "utm_source": "UTMX"}}
    vals = postback_service.build_outbound_values(conv, click, "Camp One")
    check("V1 resolves real stored values", (vals["click_id"], vals["event"], vals["payout"], vals["campaign_name"], vals["p7"], vals["ip"]) == ("QX1", "KYC", "10", "Camp One", "g", "1.2.3.4"))
    check("V2 date / date_time / country_code resolved", (vals["date"], vals["country_code"]) == ("2026-10-05", "IN") and vals["date_time"].startswith("2026-10-05T12:30"))
    check("V3 missing => None (blank): p2, state, city", vals["p2"] is None and vals["state"] is None and vals["city"] is None)
    check("V4 revenue/margin/original_rate/utm never in values", not {"revenue", "margin", "original_rate", "utm_source"} & set(vals) and "99" not in str(vals) and "UTMX" not in str(vals))
    res, _ = macro_engine.substitute_macros("https://x/?r={revenue}&u={utm_source}&e={event}", vals)
    check("V5 legacy revenue/utm macro in an old template resolves blank", res == "https://x/?r=&u=&e=KYC", res)

    # ===== 9. config precedence =====
    pub = "4821"
    async def cfg(campaign, version, enabled=True, deleted=False, url="https://x/?c={click_id}"):
        await DB_INSTANCE["publisher_postback_configs"].insert_one({"publisher_id": pub, "campaign_id": campaign, "version": version, "enabled": enabled, "deleted": deleted, "url_template": url})
    check("C1 no config -> None", await conversion_repository.get_postback_config(pub, "C1") is None)
    await cfg(None, 1, url="https://global/?c={click_id}")
    g = await conversion_repository.get_postback_config(pub, "C1")
    check("C2 only Global -> Global used", g and "global" in g["url_template"])
    await cfg("C1", 1, url="https://camp/?c={click_id}")
    check("C3 campaign-specific beats Global", "camp" in (await conversion_repository.get_postback_config(pub, "C1"))["url_template"])
    check("C4 other campaign still uses Global", "global" in (await conversion_repository.get_postback_config(pub, "C2"))["url_template"])
    await cfg("C1", 2, enabled=False)
    check("C5 campaign latest version disabled -> falls to Global (old v1 NOT resurrected)", "global" in (await conversion_repository.get_postback_config(pub, "C1"))["url_template"])
    await cfg(None, 2, enabled=False, deleted=True)
    check("C6 Global deleted -> none for any campaign", await conversion_repository.get_postback_config(pub, "C1") is None and await conversion_repository.get_postback_config(pub, "C9") is None)
    lg = await conversion_repository.get_latest_global_config(pub)
    check("C7 latest global still readable for display", lg["version"] == 2 and lg["deleted"] is True)
    await cfg(None, 3, url="https://global3/?c={click_id}")
    check("C8 re-saving Global restores it (latest version wins)", "global3" in (await conversion_repository.get_postback_config(pub, "C9"))["url_template"])
    check("C9 other publisher unaffected", await conversion_repository.get_postback_config("9999", "C1") is None)

    # ===== 10. report rows =====
    now = datetime.now(timezone.utc)
    names = {"C1": "Camp One"}
    ck = {"digisnr_click_id": "QX1", "campaign_id": "C1", "click_created_at": now, "ip": "1.2.3.4", "country": None,
          "original_params": {"p1": "alpha", "p10": "ten"}, "os": "Android", "browser": "Chrome", "device": "Phone"}
    row = report.click_row(ck, names)
    check("T1 click row: campaign name, IP, P1/P10 real, others blank", (row["campaign_name"], row["ip"], row["p1"], row["p10"], row["p5"]) == ("Camp One", "1.2.3.4", "alpha", "ten", None))
    check("T2 click row has no device/os/browser", not {"os", "browser", "device"} & set(row))
    cv = {"conversion_id": "CV1", "campaign_id": "C1", "event": "Trade", "status": "approved", "payout": 25, "revenue": 90,
          "margin": 65, "original_rate": 90, "digisnr_click_id": "QX1", "conversion_created_at": now}
    crow = report.conversion_row(cv, ck, names)
    check("T3 conversion row: ACTUAL event + payout + INR", (crow["event"], crow["payout"], crow["currency"]) == ("Trade", 25, "INR"))
    check("T4 conversion row has no revenue/margin/original_rate/device", not {"revenue", "margin", "original_rate", "os", "browser", "device"} & set(crow) and "90" not in str(crow["payout"]))
    check("T5 conversion row inherits click P values + IP", (crow["p1"], crow["p10"], crow["ip"]) == ("alpha", "ten", "1.2.3.4"))
    check("T6 missing click -> blank P/IP, no crash", report.conversion_row(cv, None, names)["p1"] is None)
    check("T7 no payout -> no currency invented", report.conversion_row({**cv, "payout": None}, ck, names)["currency"] is None)

    # ===== 11. export jobs =====
    cs = report._csv_safe
    check("E1 formula-injection guard", cs("=1+1") == "'=1+1" and cs("@x") == "'@x" and cs("+1") == "'+1" and cs("-1") == "'-1" and cs("ok") == "ok" and cs(None) == "")
    check("E2 bad kind refused", await raises(ValidationAppError, report.create_export_job("4821", "u", "x", "csv", None, None, None, False)))
    check("E3 bad format refused", await raises(ValidationAppError, report.create_export_job("4821", "u", "clicks", "xml", None, None, None, False)))
    check("E4 >90-day range refused", await raises(ValidationAppError, report.create_export_job("4821", "u", "clicks", "csv", None, "2026-01-01", "2026-06-01", False)))
    check("E5 inverted range refused", await raises(ValidationAppError, report.create_export_job("4821", "u", "clicks", "csv", None, "2026-02-01", "2026-01-01", False)))
    DB_INSTANCE["campaigns"].docs.clear()
    for i, (ip, p1) in enumerate([("1.1.1.1", "=HYPERLINK(\"x\")"), ("1.1.1.1", "b"), ("2.2.2.2", None)]):
        await DB_INSTANCE["clicks"].insert_one({"digisnr_click_id": f"QXE{i}", "publisher_id": "4821", "campaign_id": "C1", "ip": ip,
                                                 "click_created_at": now - timedelta(minutes=i), "original_params": {"p1": p1} if p1 else {}})
    await DB_INSTANCE["clicks"].insert_one({"digisnr_click_id": "OTHER", "publisher_id": "7777", "campaign_id": "C1", "ip": "9.9.9.9", "click_created_at": now, "original_params": {}})
    job = await report.create_export_job("4821", "u", "clicks", "csv", None, None, None, False)
    check("E6 job created PENDING with EXP id", job["status"] == "PENDING" and report.re.fullmatch(r"EXP[A-Z0-9]{10}", job["job_id"]) is not None)
    check("E7 request audited (no secrets)", any(a == "EXPORT_JOB_REQUESTED" for a, _ in audit_log))
    await report.run_export_job(job["job_id"])
    await report.run_export_job(job["job_id"])  # second trigger must be a no-op
    stored = await DB_INSTANCE["export_jobs"].find_one({"job_id": job["job_id"]})
    check("E8 job COMPLETED with exact record count (own clicks only)", stored["status"] == "COMPLETED" and stored["records"] == 3, str(stored["records"]))
    content = stored["content"]
    check("E9 CSV header has P1-P10, no device/os/browser", content.splitlines()[0].startswith("Date,Click ID,Campaign") and "P10" in content.splitlines()[0] and not any(x in content.splitlines()[0] for x in ("Device", "OS", "Browser")))
    check("E10 other publisher's click not exported; formula neutralised", "OTHER" not in content and "'=HYPERLINK" in content)
    uj = await report.create_export_job("4821", "u", "clicks", "json", None, None, None, True)
    await report.run_export_job(uj["job_id"])
    sj = await DB_INSTANCE["export_jobs"].find_one({"job_id": uj["job_id"]})
    check("E11 unique-IP export de-duplicates (2 unique IPs)", sj["records"] == 2, str(sj["records"]))
    lst = await report.list_jobs("4821", "clicks")
    check("E12 list is owner-scoped, excludes content, newest first", len(lst) == 2 and all("content" not in j for j in lst) and lst[0]["job_id"] == uj["job_id"])
    check("E13 other publisher sees none", await report.list_jobs("7777", None) == [])
    check("E14 other publisher cannot download my job", await raises(NotFoundError, report.get_job_content("7777", job["job_id"])))
    check("E15 malformed job id -> not found", await raises(NotFoundError, report.get_job_content("4821", "../etc/passwd")))
    j, body = await report.get_job_content("4821", job["job_id"])
    check("E16 owner downloads own content", "QXE0" in body)
    for _ in range(3):
        await DB_INSTANCE["export_jobs"].insert_one({"job_id": "EXP" + "A" * 10, "publisher_id": "5555", "status": "PENDING"})
    check("E17 more than 3 active jobs refused", await raises(ConflictError, report.create_export_job("5555", "u", "clicks", "csv", None, None, None, False)))
    # conversions export has Currency + Event but never revenue/margin
    await DB_INSTANCE["conversions"].insert_one({"conversion_id": "CVX", "publisher_id": "4821", "campaign_id": "C1", "event": "Register", "status": "approved",
                                                 "payout": 10, "revenue": 77, "digisnr_click_id": "QXE1", "conversion_created_at": now})
    cj = await report.create_export_job("4821", "u", "conversions", "csv", None, None, None, False)
    await report.run_export_job(cj["job_id"])
    sc = await DB_INSTANCE["export_jobs"].find_one({"job_id": cj["job_id"]})
    check("E18 conversions export: actual event, payout, INR, no revenue", sc["status"] == "COMPLETED" and "Register" in sc["content"] and "INR" in sc["content"] and "77" not in sc["content"], str(sc.get("error")))
    # failed job recorded, not silent
    bad_job = await report.create_export_job("4821", "u", "clicks", "csv", None, None, None, False)
    orig = report.click_row
    report.click_row = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    await report.run_export_job(bad_job["job_id"])
    report.click_row = orig
    fj = await DB_INSTANCE["export_jobs"].find_one({"job_id": bad_job["job_id"]})
    check("E19 failure recorded as FAILED with safe message", fj["status"] == "FAILED" and "boom" not in str(fj["error"]))

    # ===== 12. audit vocabulary =====
    for name in ("PUBLISHER_MANAGER_REASSIGNED", "WHATSAPP_GROUP_LINK_UPDATED", "GLOBAL_POSTBACK_SAVED", "GLOBAL_POSTBACK_DELETED", "EXPORT_JOB_REQUESTED", "MANAGER_MOBILE_UPDATED"):
        check(f"D1 audit action defined: {name}", hasattr(audit_actions, name))


def _wrap(fn, *a):
    async def _c():
        fn(*a)
    return _c()


asyncio.run(main())
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
