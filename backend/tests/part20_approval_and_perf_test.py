"""
Part 20 - approval-only registration/login + dashboard latency.

Real modules under test: app/services/auth_service.py (login/refresh), app/core/rbac.py
(get_current_user), app/services/dashboard_service.py (get_dashboard).
Stubbed: fastapi/jose/bcrypt (not installable offline) and the storage layer, which is an
in-memory fake with INJECTABLE LATENCY per call, so "how many round trips are on the critical
path" can be measured deterministically. No network, no secrets.

Latency note: the numbers below are SIMULATED round trips (each fake call sleeps LAT seconds).
They prove the critical path shrank (e.g. 12 sequential calls -> 2-3 stages); they are NOT a
measurement of the real storage service.
"""
import asyncio
import enum
import importlib.util
import os
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' - ' + str(detail)) if detail and not ok else ''}")


def mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


class HTTPException(Exception):
    def __init__(self, status_code, detail=None):
        self.status_code, self.detail = status_code, detail


STATUS = NS(HTTP_400_BAD_REQUEST=400, HTTP_401_UNAUTHORIZED=401, HTTP_403_FORBIDDEN=403, HTTP_404_NOT_FOUND=404,
            HTTP_409_CONFLICT=409, HTTP_422_UNPROCESSABLE_ENTITY=422, HTTP_429_TOO_MANY_REQUESTS=429,
            HTTP_503_SERVICE_UNAVAILABLE=503)
mod("fastapi", Depends=lambda f=None: f, HTTPException=HTTPException, status=STATUS, Request=object)
mod("fastapi.responses", JSONResponse=object)
mod("fastapi.security", HTTPAuthorizationCredentials=object, HTTPBearer=lambda auto_error=True: object())
for n in ("app", "app.core", "app.db", "app.services"):
    mod(n)
load("app.core.enums", "app/core/enums.py")
load("app.core.exceptions", "app/core/exceptions.py")
load("app.core.audit_actions", "app/core/audit_actions.py")
load("app.core.email_utils", "app/core/email_utils.py")
from app.core.enums import AccountStatus, Role  # noqa: E402

# ----- fake data + latency -----
LAT = 0.05
calls = {"n": 0}
USERS = {}
SESSIONS = {}
audit = []
issued = []


async def rt():
    calls["n"] += 1
    await asyncio.sleep(LAT)


def mk_user(uid, email, role, st, pw="pw"):
    USERS[uid] = NS(id=uid, email=email, role=role, account_status=st, password_hash="H:" + pw)


async def get_user_by_email(email):
    await rt()
    return next((u for u in USERS.values() if u.email == email), None)


async def get_user_by_id(uid):
    await rt()
    return USERS.get(uid)


async def create_session(uid, jti):
    await rt()
    SESSIONS[jti] = {"user_id": uid, "revoked": False}


async def get_session(jti):
    await rt()
    return SESSIONS.get(jti)


mod("app.db.user_repository", get_user_by_email=get_user_by_email, get_user_by_id=get_user_by_id)
async def revoke_session(jti):
    SESSIONS.get(jti, {})["revoked"] = True


mod("app.db.session_repository", create_session=create_session, get_session=get_session, revoke_session=revoke_session,
    is_session_live=lambda s: bool(s) and not s["revoked"], revoke_all_sessions_for_user=None)
sys.modules["app.db"].user_repository = sys.modules["app.db.user_repository"]
sys.modules["app.db"].session_repository = sys.modules["app.db.session_repository"]


async def audit_record(action, **kw):
    audit.append((action, kw))


mod("app.db.audit_repository", record=audit_record)
mod("app.db.mongodb", get_database=lambda: None)
mod("app.services.email_service")
mod("app.services.otp_service")
sys.modules["app.services"].email_service = sys.modules["app.services.email_service"]
sys.modules["app.services"].otp_service = sys.modules["app.services.otp_service"]


def create_refresh_token(uid, role):
    jti = f"jti-{len(issued)}"
    return f"R:{jti}", jti


def create_access_token(uid, role, sid=None):
    issued.append((uid, sid))
    return f"A:{sid}"


def decode_token(tok, expected_type=None):
    if tok.startswith("A:"):
        sid = tok[2:]
        return {"sub": SESSIONS.get(sid, {}).get("user_id", "ghost"), "sid": sid}
    raise HTTPException(401, "bad token")


mod("app.core.security", create_access_token=create_access_token, create_refresh_token=create_refresh_token,
    decode_token=decode_token, hash_password=lambda p: "H:" + p, verify_password=lambda p, h: h == "H:" + p)
rbac = load("app.core.rbac", "app/core/rbac.py")
auth_service = load("app.services.auth_service", "app/services/auth_service.py")
UnauthorizedError = sys.modules["app.core.exceptions"].UnauthorizedError


async def login_err(email, pw):
    try:
        await auth_service.login(email, pw)
    except UnauthorizedError as e:
        return e.message
    return None


async def main():
    mk_user("u1", "pending@x.com", Role.PUBLISHER, AccountStatus.PENDING, "Secret1!")
    mk_user("u2", "rejected@x.com", Role.PUBLISHER, AccountStatus.REJECTED, "Secret1!")
    mk_user("u3", "active@x.com", Role.PUBLISHER, AccountStatus.ACTIVE, "Secret1!")
    mk_user("u4", "susp@x.com", Role.MANAGER, AccountStatus.SUSPENDED if hasattr(AccountStatus, "SUSPENDED") else AccountStatus.REJECTED, "Secret1!")

    # ===== login behaviour =====
    msg = await login_err("pending@x.com", "Secret1!")
    check("A1 PENDING login shows the exact approval message", msg == "Your account is pending Super Admin approval.", msg)
    check("A2 PENDING login issued NO token / session", not issued and not SESSIONS)
    msg = await login_err("rejected@x.com", "Secret1!")
    check("A3 REJECTED login shows the exact rejection message", msg == "Your account registration has been rejected.", msg)
    check("A4 REJECTED login issued NO token / session", not issued and not SESSIONS)
    msg = await login_err("pending@x.com", "wrong-password")
    check("A5 wrong password on a PENDING account reveals nothing (generic error)", msg == "Invalid email or password", msg)
    msg = await login_err("nobody@x.com", "Secret1!")
    check("A6 unknown email -> same generic error (no account enumeration)", msg == "Invalid email or password", msg)
    res = await auth_service.login("active@x.com", "Secret1!")
    check("A7 ACTIVE user logs in with registered email + password and gets a session", res.access_token and len(SESSIONS) == 1)
    check("A8 failed PENDING/REJECTED attempts were audited", sum(1 for a, _ in audit if a == "LOGIN_FAILED") >= 4)

    # ===== backend enforcement on every request =====
    tok = res.access_token
    creds = NS(credentials=tok)
    me = await rbac.get_current_user(creds)
    check("B1 valid ACTIVE session passes get_current_user", me.user_id == "u3" and me.role == Role.PUBLISHER)
    USERS["u3"].account_status = AccountStatus.PENDING  # demoted after login
    try:
        await rbac.get_current_user(creds)
        ok = False
    except HTTPException as e:
        ok = e.status_code == 403
    check("B2 an existing token stops working when the account is no longer ACTIVE (DB-authoritative)", ok)
    USERS["u3"].account_status = AccountStatus.ACTIVE
    SESSIONS[list(SESSIONS)[0]]["revoked"] = True
    try:
        await rbac.get_current_user(creds)
        ok = False
    except HTTPException as e:
        ok = e.status_code == 401
    check("B3 revoked session is refused (401)", ok)
    try:
        await rbac.get_current_user(NS(credentials="A:forged"))
        ok = False
    except HTTPException as e:
        ok = e.status_code == 401
    check("B4 token for an unknown session is refused, even though the user lookup also ran", ok)
    try:
        await rbac.get_current_user(None)
        ok = False
    except HTTPException as e:
        ok = e.status_code == 401
    check("B5 no token -> 401", ok)
    # role check
    dep = rbac.require_role(Role.SUPER_ADMIN)
    try:
        dep(NS(user_id="u3", role=Role.PUBLISHER, account_status=AccountStatus.ACTIVE))
        ok = False
    except HTTPException as e:
        ok = e.status_code == 403
    check("B6 a Publisher cannot reach a Super Admin-only dependency (403)", ok)

    # refresh must not resurrect a non-active account
    USERS["u3"].account_status = AccountStatus.REJECTED
    SESSIONS["live"] = {"user_id": "u3", "revoked": False}
    refresh_tok = "R:live"
    sys.modules["app.core.security"].decode_token = lambda t, expected_type=None: {"sub": "u3", "jti": "live"}
    auth_service.decode_token = sys.modules["app.core.security"].decode_token
    try:
        await auth_service.refresh(refresh_tok)
        ok = False
    except UnauthorizedError:
        ok = True
    check("B7 refresh is refused for a REJECTED account (no new tokens)", ok)

    # ===== latency: critical path =====
    USERS["u3"].account_status = AccountStatus.ACTIVE
    SESSIONS["s9"] = {"user_id": "u3", "revoked": False}
    calls["n"] = 0
    t0 = time.perf_counter()
    await rbac.get_current_user(NS(credentials="A:s9"))
    dt = time.perf_counter() - t0
    check("P1 auth check costs ONE round trip of latency (session + user fetched concurrently)", dt < LAT * 1.6 and calls["n"] == 2, f"{dt:.3f}s calls={calls['n']}")

    # dashboard: eight independent counts
    class Col:
        async def count_documents(self, q):
            await rt()
            return 1

    campaign_repository = mod("app.db.campaign_repository")

    async def c1():
        await rt()
        return 2

    campaign_repository.count_all_campaigns = c1
    campaign_repository.count_campaigns_by_status = lambda s: c1()
    sys.modules["app.db"].campaign_repository = campaign_repository
    mod("app.db.mongodb", get_database=lambda: {"users": Col()})
    ds = load("app.services.dashboard_service", "app/services/dashboard_service.py")
    calls["n"] = 0
    t0 = time.perf_counter()
    data = await ds.get_dashboard()
    dt = time.perf_counter() - t0
    check("P2 admin dashboard: 8 reads issued concurrently (~1 round trip, was 8 in a row)", dt < LAT * 2.5 and calls["n"] == 8, f"{dt:.3f}s calls={calls['n']}")
    k = data["kpis"]
    check("P3 dashboard numbers unchanged (real counts, same keys)", k["total_managers"]["value"] == 1 and k["active_campaigns"]["value"] == 2
          and set(data["pending_approvals"]) == {"managers", "publishers"})

    print(f"\nSimulated round-trip latency: {LAT * 1000:.0f} ms per storage call.")
    passed = sum(results)
    print(f"{passed}/{len(results)} passed")
    return passed == len(results)


sys.exit(0 if asyncio.run(main()) else 1)
