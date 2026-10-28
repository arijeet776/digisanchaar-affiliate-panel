"""Part 24 - STORAGE_BACKEND=supabase_rest config guards (real app/config.py; pydantic_settings shimmed; keys generated in memory)."""
import base64, importlib.util, json, os, secrets, sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
res = []
def check(n, ok, d=""):
    res.append(bool(ok)); print(f"[{'PASS' if ok else 'FAIL'}] {n}" + (f" - {d}" if d and not ok else ""))
from pydantic import BaseModel, ConfigDict
class BaseSettings(BaseModel):
    def __init__(self, **kw):
        for fname, f in type(self).model_fields.items():
            if fname in kw: continue
            names = [fname.upper()]; alias = f.validation_alias
            if alias is not None and hasattr(alias, "choices"): names = [str(c).upper() for c in alias.choices]
            for n in names:
                if n in os.environ: kw[n if alias is not None else fname] = os.environ[n]; break
        super().__init__(**kw)
m = types.ModuleType("pydantic_settings"); m.BaseSettings = BaseSettings; m.SettingsConfigDict = lambda **k: ConfigDict(extra="ignore"); sys.modules["pydantic_settings"] = m
spec = importlib.util.spec_from_file_location("qcfg", ROOT / "app/config.py"); cfg = importlib.util.module_from_spec(spec); spec.loader.exec_module(cfg)

def jwt(role):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b({'alg':'HS256'})}.{b({'role': role})}.{secrets.token_urlsafe(20)}"
def attempt(**env):
    base = {"JWT_SECRET_KEY": secrets.token_urlsafe(40), "STORAGE_BACKEND": "supabase_rest", "SUPABASE_URL": "https://abc.supabase.co", "SUPABASE_SERVICE_KEY": "sb_secret_" + secrets.token_urlsafe(30)}
    base.update(env)
    for k in [k for k in os.environ if k.startswith(("SUPABASE_", "STORAGE_", "ENVIRONMENT", "JWT_", "ALLOWED_", "MONGO", "POSTGRES"))]: del os.environ[k]
    os.environ.update({k: v for k, v in base.items() if v is not None})
    try: cfg.Settings(); return None
    except Exception as e: return str(e)
check("K1 valid secret key accepted", attempt() is None)
check("K2 publishable key REJECTED", "publishable" in (attempt(SUPABASE_SERVICE_KEY="sb_publishable_" + secrets.token_urlsafe(20)) or ""))
check("K3 legacy anon JWT REJECTED", "anon" in (attempt(SUPABASE_SERVICE_KEY=jwt("anon")) or "") or "publishable/anon" in (attempt(SUPABASE_SERVICE_KEY=jwt("anon")) or ""))
check("K4 legacy service_role JWT accepted", attempt(SUPABASE_SERVICE_KEY=jwt("service_role")) is None)
check("K5 missing key refused", attempt(SUPABASE_SERVICE_KEY="short") is not None)
check("K6 http:// URL refused", attempt(SUPABASE_URL="http://abc.supabase.co") is not None)
check("K7 missing URL refused", attempt(SUPABASE_URL=None) is not None)
prod = dict(ENVIRONMENT="production", ALLOWED_ORIGINS="https://app.example.com", JWT_SECRET_KEY=secrets.token_urlsafe(40))
check("K8 production needs no Mongo/Postgres vars in supabase_rest mode", attempt(**prod) is None)
check("K9 production still forbids wildcard CORS", attempt(**{**prod, "ALLOWED_ORIGINS": "*"}) is not None)
check("K10 unknown backend refused", attempt(STORAGE_BACKEND="nope") is not None)
print(f"{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
