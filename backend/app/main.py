import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging_config import configure_logging
from app.db.mongodb import close_mongo_connection, connect_to_mongo
from app.db.postgres import close_postgres_connection, connect_to_postgres, ping_postgres
from app.middleware.request_id import RequestIdMiddleware

settings = get_settings()
configure_logging(settings.environment.value)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up in %s environment", settings.environment.value)
    await connect_to_mongo()
    await connect_to_postgres()
    # Part 9 — financial schema migrations. Best-effort like every other
    # startup step here: if Postgres isn't reachable yet, this is a no-op
    # and /health/ready already reflects that; migrations are retried the
    # next time the process starts once Postgres is reachable.
    if await ping_postgres():
        from app.db.migrations import run_migrations_safely

        await run_migrations_safely()
    yield
    await close_mongo_connection()
    await close_postgres_connection()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.brand_name,
        version="0.1.0",
        lifespan=lifespan,
        # Hide interactive docs in production (spec §59 — reduce attack surface)
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Server-Timing"],
    )
    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app)

    @app.middleware("http")
    async def server_timing(request, call_next):
        """Measures where request time goes. `Server-Timing: total;dur=..., storage;dur=..;desc="N calls"`.
        Only durations and a call count - never request data, tokens or secrets."""
        import time

        from app.storage import runtime as _runtime

        started = time.perf_counter()
        stats = None
        if _runtime.uses_adapter():
            from app.storage.storage_adapter import begin_request_stats

            stats = begin_request_stats()
        response = await call_next(request)
        parts = [f"total;dur={(time.perf_counter() - started) * 1000:.0f}"]
        if stats is not None:
            parts.append(f'storage;dur={stats["ms"]:.0f};desc="{stats["calls"]} calls"')
        response.headers["Server-Timing"] = ", ".join(parts)
        return response

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-XSS-Protection", "0")
        return response

    app.include_router(api_router, prefix="/api/v1")

    # Public short tracking URL at the domain root (master spec §20):
    # https://{tracking-domain}/{campaign-code}/{public-link-code}
    # In production the tracking domain points directly at the backend; the
    # same handler is also reachable at /api/v1/t/... for environments where
    # it is not pointed yet. Two path segments can never collide with the
    # /api/v1/* API surface.
    from app.api.v1.endpoints.click import click_route_dependencies, handle_click

    app.add_api_route(
        "/{campaign_code}/{link_code}",
        handle_click,
        methods=["GET"],
        dependencies=click_route_dependencies,
        include_in_schema=False,
    )

    return app


app = create_app()
