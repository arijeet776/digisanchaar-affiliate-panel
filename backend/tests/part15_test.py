"""
Part 15 test — production configuration guards and readiness reporting.
    python3 tests/part15_test.py
Needs the app dependencies (pydantic-settings, motor, mongomock-motor). It has
NOT been executed in the authoring sandbox (package registry blocked); run it
in the real environment.
"""
import asyncio
import os
import sys

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-prod")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("ENVIRONMENT", "development")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, condition, detail=""):
    s = "PASS" if condition else "FAIL"
    results.append((name, s, detail))
    print(f"[{s}] {name}" + (f" — {detail}" if detail else ""))
    return condition


# Init kwargs use field names (allowed_origins is populated via its alias).
GOOD = dict(
    environment="production",
    jwt_secret_key="a" * 8 + "f3c1" * 8,
    mongo_uri="mongodb://db.internal:27017",
    mongo_db_name="quantix_prod",
    postgres_dsn="postgresql://svc:pw@pg.internal:5432/quantix",
    ALLOWED_ORIGINS="https://app.example.com",
)


def build(**over):
    from app.config import Settings

    return Settings(_env_file=None, **{**GOOD, **over})


def rejects(**over):
    try:
        build(**over)
        return False
    except Exception:
        return True


async def main():
    ok = build()
    check("P15-1: fully configured production settings load", ok.is_production)
    check("P15-2: short JWT secret rejected", rejects(jwt_secret_key="short"))
    check("P15-3: placeholder-looking JWT secret rejected", rejects(jwt_secret_key="change-me-" + "x" * 30))
    check("P15-4: wildcard CORS rejected", rejects(ALLOWED_ORIGINS="*"))
    check("P15-5: dev Postgres placeholder rejected", rejects(postgres_dsn="postgresql://user:password@localhost:5432/quantix_dev"))
    # Env vars would count as "explicitly set"; hide them for the missing-variable checks.
    saved = {k: os.environ.pop(k) for k in ("MONGO_URI", "MONGO_DB_NAME", "POSTGRES_DSN") if k in os.environ}
    for missing in ("mongo_uri", "mongo_db_name", "postgres_dsn"):
        from app.config import Settings

        kw = {k: v for k, v in GOOD.items() if k != missing}
        try:
            Settings(_env_file=None, **kw)
            bad = False
        except Exception:
            bad = True
        check(f"P15-6: production without explicit {missing.upper()} refuses to start", bad)
    os.environ.update(saved)
    os.environ["CORS_ALLOWED_ORIGINS"] = "https://alias.example.com"
    from app.config import Settings

    alias_ok = Settings(_env_file=None, jwt_secret_key="x" * 40).allowed_origins_list
    os.environ.pop("CORS_ALLOWED_ORIGINS")
    check("P15-7: CORS_ALLOWED_ORIGINS env alias is honoured", alias_ok == ["https://alias.example.com"], str(alias_ok))

    # Readiness reports index + migration state and stays 503 without Postgres
    from mongomock_motor import AsyncMongoMockClient
    import app.db.mongodb as mongodb_module
    from httpx import AsyncClient, ASGITransport
    from app.main import create_app

    c = AsyncMongoMockClient()
    mongodb_module._client = c
    mongodb_module._db = c["quantix_test_part15"]
    mongodb_module._indexes_ready = False
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        live = await client.get("/api/v1/health/live")
        check("P15-8: /health/live is 200 and dependency-free", live.status_code == 200)
        r = await client.get("/api/v1/health/ready")
        j = r.json()
        check("P15-9: /health/ready is 503 when Postgres is unavailable", r.status_code == 503 and j["postgres"] == "error", str(j))
        check("P15-10: readiness retries and reports Mongo index creation", j.get("mongo_indexes") == "ok" and mongodb_module._indexes_ready)
        check("P15-11: readiness reports migration status without leaking infra detail",
              j.get("migrations") == "pending" and "dsn" not in str(j).lower() and "uri" not in str(j).lower())

    failed = [x for x in results if x[1] == "FAIL"]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
