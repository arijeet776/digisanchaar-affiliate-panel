"""
Part 16.2 test — global accent theme persistence logic (default, validation,
fallback, audit). Self-contained: the service's collaborators are stubbed, so
it needs no database or third-party packages.
    python3 tests/part16_2_theme_test.py
"""
import asyncio
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ---- stub collaborators --------------------------------------------------
store: dict = {}
audit_calls: list = []
fail_reads = {"on": False}


class ValidationAppError(Exception):
    pass


def mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


mod("app"); mod("app.core"); mod("app.db")
mod("app.config", get_settings=lambda: types.SimpleNamespace(tracking_base_url=None, is_production=False))
mod("app.core.audit_actions", TRACKING_DOMAIN_UPDATED="X", ACCENT_THEME_UPDATED="ACCENT_THEME_UPDATED")
mod("app.core.exceptions", ValidationAppError=ValidationAppError)


async def get_setting(key):
    if fail_reads["on"]:
        raise RuntimeError("store down")
    return store.get(key)


async def upsert_setting(key, value, by):
    store[key] = {"key": key, "value": value, "updated_at": "now", "updated_by": by}
    return store[key]


async def audit_record(action, **kw):
    audit_calls.append((action, kw))


mod("app.db.settings_repository", get_setting=get_setting, upsert_setting=upsert_setting,
    TRACKING_DOMAIN_KEY="tracking_base_url", ACCENT_THEME_KEY="accent_theme")
sys.modules["app.db"].settings_repository = sys.modules["app.db.settings_repository"]
mod("app.db.audit_repository", record=audit_record)

spec = importlib.util.spec_from_file_location("settings_service", os.path.join(ROOT, "app/services/settings_service.py"))
svc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(svc)


async def main():
    r = await svc.get_accent_theme()
    check("P16.2-1 default is deep-yellow when nothing stored", r["accent_theme"] == "deep-yellow" and r["is_default"])
    check("P16.2-2 four stable theme ids", svc.ACCENT_THEMES == ("deep-yellow", "deep-sky", "deep-orange", "hasmind-purple"))

    out = await svc.update_accent_theme("deep-orange", "admin-1")
    check("P16.2-3 update persists and returns value", out["accent_theme"] == "deep-orange" and store["accent_theme"]["value"] == "deep-orange")
    check("P16.2-4 read returns saved value (not default)", (await svc.get_accent_theme()) ["accent_theme"] == "deep-orange")
    check("P16.2-5 change is audited with before/after",
          audit_calls and audit_calls[-1][0] == "ACCENT_THEME_UPDATED"
          and audit_calls[-1][1]["before"] == {"accent_theme": "deep-yellow"}
          and audit_calls[-1][1]["after"] == {"accent_theme": "deep-orange"})

    try:
        await svc.update_accent_theme("neon-green", "admin-1")
        check("P16.2-6 invalid theme rejected", False)
    except ValidationAppError:
        check("P16.2-6 invalid theme rejected", True)
    check("P16.2-7 rejected value not stored", store["accent_theme"]["value"] == "deep-orange")

    store["accent_theme"]["value"] = "garbage"
    check("P16.2-8 corrupt stored value falls back to default", (await svc.get_accent_theme())["accent_theme"] == "deep-yellow")

    fail_reads["on"] = True
    check("P16.2-9 store outage never breaks (default served)", (await svc.get_accent_theme())["accent_theme"] == "deep-yellow")


asyncio.run(main())
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
