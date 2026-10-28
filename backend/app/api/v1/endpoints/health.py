"""
Liveness vs readiness (Part 1 review fix).

/health/live  - "is the process up and able to handle a request at all?"
                Never touches a dependency. If this doesn't return 200, the
                only correct response is to restart the process.

/health/ready - "can this instance actually serve business traffic right
                now?" Checks Mongo + Postgres. Returns 503 (not 200) when a
                dependency is down, so an orchestrator can stop routing
                traffic here without killing/restarting the process.

This split only works because app startup no longer fails hard when a DB is
unreachable (see app/db/mongodb.py, app/db/postgres.py) — otherwise /live
would never be reachable to answer in the first place.
"""
from fastapi import APIRouter, Response, status

from app.config import get_settings
from app.db import migrations
from app.db.mongodb import ping_mongo, retry_indexes_if_needed
from app.db.postgres import ping_postgres

router = APIRouter()


@router.get("/live")
async def liveness():
    return {"status": "alive"}


@router.get("/ready")
async def readiness(response: Response):
    settings = get_settings()
    mongo_ok = await ping_mongo()
    postgres_ok = await ping_postgres()
    indexes_ok = await retry_indexes_if_needed() if mongo_ok else False
    migrations_status = (await migrations.retry_if_needed()) if postgres_ok else "pending"
    ready = mongo_ok and postgres_ok and indexes_ok and migrations_status == "ok"

    response.status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "environment": settings.environment.value,
        "storage_backend": settings.storage_backend,  # name only: lets you confirm which storage mode is active
        "mongo": "ok" if mongo_ok else "error",
        "postgres": "ok" if postgres_ok else "error",
        "mongo_indexes": "ok" if indexes_ok else "pending",
        "migrations": migrations_status,
    }
