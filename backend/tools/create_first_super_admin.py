"""
One-time, interactive first Super Admin provisioning (NOT an API route).

Run on a trusted machine/shell that has the backend's env vars (same ones the API uses):
    cd backend && python -m tools.create_first_super_admin --email you@example.com

Safety properties (enforced in provision(), covered by tests/part21_first_admin_test.py):
  * the password is read with getpass (twice), never from argv/env, never printed or logged;
  * hashed with the app's own hash_password (same bcrypt context as login);
  * role/status come from the real enums (Role.SUPER_ADMIN / AccountStatus.ACTIVE);
  * refuses if the email already exists, or if ANY active super_admin already exists
    (override only with --allow-additional, still never touches an existing row);
  * inserts exactly ONE new users document; no other account/collection is modified
    except one append-only audit_logs entry (no password in it);
  * works with whichever STORAGE_BACKEND is configured (Supabase REST adapter or Mongo).
"""
import argparse
import asyncio
import getpass
import sys
from datetime import datetime, timezone

from app.core.audit_actions import USER_REGISTERED
from app.core.email_utils import normalize_email
from app.core.enums import AccountStatus, Role

AUDIT_ACTION = "SUPER_ADMIN_BOOTSTRAPPED"
MIN_PASSWORD_LEN = 12


class ProvisionError(Exception):
    pass


def validate_password(pw: str) -> None:
    if len(pw) < MIN_PASSWORD_LEN:
        raise ProvisionError(f"Password must be at least {MIN_PASSWORD_LEN} characters")
    if not (any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw)):
        raise ProvisionError("Password needs upper-case, lower-case and a digit")


async def provision(db, email: str, password: str, hash_fn, audit_fn=None, allow_additional: bool = False) -> str:
    email = normalize_email(email)
    if "@" not in email or " " in email:
        raise ProvisionError("Invalid email address")
    validate_password(password)
    users = db["users"]
    if await users.find_one({"email": email}):
        raise ProvisionError("A user with this email already exists; nothing was changed")
    if not allow_additional and await users.find_one({"role": Role.SUPER_ADMIN.value, "account_status": AccountStatus.ACTIVE.value}):
        raise ProvisionError("An active Super Admin already exists; nothing was changed")
    now = datetime.now(timezone.utc)
    doc = {
        "email": email,
        "password_hash": hash_fn(password),
        "role": Role.SUPER_ADMIN.value,
        "account_status": AccountStatus.ACTIVE.value,
        "email_verified": True,
        "created_at": now,
        "updated_at": now,
    }
    res = await users.insert_one(doc)
    uid = str(res.inserted_id)
    if audit_fn:
        await audit_fn(AUDIT_ACTION, actor_user_id=None, target_user_id=uid,
                       after={"role": Role.SUPER_ADMIN.value, "account_status": AccountStatus.ACTIVE.value},
                       metadata={"via": "cli", "event": USER_REGISTERED})
    return uid


async def _run(args) -> int:
    from app.core.security import hash_password
    from app.db import audit_repository
    from app.db.mongodb import connect_to_mongo, get_database

    pw = getpass.getpass("New Super Admin password (hidden): ")
    if pw != getpass.getpass("Repeat password: "):
        print("Passwords do not match; nothing was changed.", file=sys.stderr)
        return 1
    await connect_to_mongo()
    db = get_database()
    print(f"About to create ONE Super Admin: {normalize_email(args.email)}")
    if not args.yes and input("Type CREATE to continue: ").strip() != "CREATE":
        print("Aborted; nothing was changed.")
        return 1
    try:
        uid = await provision(db, args.email, pw, hash_password, audit_repository.record, args.allow_additional)
    except ProvisionError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    print(f"Created Super Admin id={uid}. You can log in with that email and the password you typed.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True)
    ap.add_argument("--allow-additional", action="store_true", help="permit creating another Super Admin when one is already active")
    ap.add_argument("--yes", action="store_true", help="skip the CREATE confirmation (password prompt stays interactive)")
    sys.exit(asyncio.run(_run(ap.parse_args())))


if __name__ == "__main__":
    main()
