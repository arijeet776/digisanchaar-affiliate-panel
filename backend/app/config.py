"""
Single source of truth for configuration.

All env vars are read here, once. Nothing else in the codebase should call
os.environ directly — that keeps environment separation (dev/staging/prod)
enforceable in one place instead of scattered across modules.
"""
from enum import Enum
from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


# Substrings that mark a JWT secret as a copied example/test value.
_INSECURE_SECRET_MARKERS = ("change-me", "changeme", "not-for-prod", "test-secret", "placeholder", "example", "your-secret", "your_secret")


def _jwt_role(token: str) -> str | None:
    """Unverified peek at a legacy Supabase JWT key's `role` claim (config sanity check only)."""
    import base64
    import json

    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        pad = "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(parts[1] + pad)).get("role")
    except Exception:  # noqa: BLE001
        return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Environment = Environment.DEVELOPMENT

    # Mongo (operational store)
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "digisanchaar_dev"

    # Storage backend switch. "mongodb_supabase" (default) = MongoDB + Postgres/Supabase (direct drivers);
    # "supabase_rest" = Supabase over HTTPS only (recommended for Render).
    storage_backend: str = "mongodb_supabase"

    # "supabase_rest": Supabase over HTTPS only (PostgREST). The SERVER-SIDE secret / service_role key is
    # required; the publishable (anon) key is rejected. Never put either key in the frontend / VITE_*.
    supabase_url: str | None = None
    supabase_service_key: str | None = None
    supabase_timeout_seconds: float = 15.0

    # Postgres / Supabase (financial system of record)
    postgres_dsn: str = "postgresql://user:password@localhost:5432/digisanchaar_dev"

    # Auth
    jwt_secret_key: str = Field(..., description="Must be set explicitly per environment")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # CORS — comma-separated origins. Env var ALLOWED_ORIGINS (or the alias
    # CORS_ALLOWED_ORIGINS). No wildcard in production (see _production_guards).
    allowed_origins: str = Field(
        default="http://localhost:5173",
        validation_alias=AliasChoices("ALLOWED_ORIGINS", "CORS_ALLOWED_ORIGINS"),
    )

    # Branding (spec §57 — configurable, never hard-coded in logic)
    brand_name: str = "DigiSanchaar"

    # Tracking (spec §29) — bootstrap/default only. The DB-backed value set
    # via System Settings → Domain & Tracking is authoritative at runtime.
    tracking_base_url: str | None = None

    @model_validator(mode="after")
    def _storage_guards(self) -> "Settings":
        if self.storage_backend not in ("mongodb_supabase", "supabase_rest"):
            raise ValueError("STORAGE_BACKEND must be 'mongodb_supabase' or 'supabase_rest'")
        if self.storage_backend == "supabase_rest":
            if not self.supabase_url or not self.supabase_url.startswith("https://"):
                raise ValueError("SUPABASE_URL must be set to the https project URL")
            key = self.supabase_service_key or ""
            if len(key) < 20:
                raise ValueError("SUPABASE_SERVICE_KEY must be set (server-side secret / service_role key)")
            if key.startswith("sb_publishable_") or _jwt_role(key) == "anon":
                raise ValueError("SUPABASE_SERVICE_KEY is a publishable/anon key; the backend needs the secret/service_role key")
        return self

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        """Fail closed at startup if production is configured unsafely.
        Development/test behaviour is unchanged."""
        if self.environment == Environment.PRODUCTION:
            if len(self.jwt_secret_key) < 32:
                raise ValueError("JWT_SECRET_KEY must be at least 32 characters in production")
            lowered = self.jwt_secret_key.lower()
            if any(marker in lowered for marker in _INSECURE_SECRET_MARKERS):
                raise ValueError("JWT_SECRET_KEY looks like a placeholder; set a random value in production")
            # The localhost defaults exist for development only. In production
            # the operator must set these explicitly, never fall back silently.
            for name in (() if self.storage_backend == "supabase_rest" else ("mongo_uri", "mongo_db_name", "postgres_dsn")):
                if name not in self.model_fields_set:
                    raise ValueError(f"{name.upper()} must be set explicitly in production")
            if "*" in self.allowed_origins_list:
                raise ValueError("ALLOWED_ORIGINS must not contain '*' in production")
            if self.storage_backend == "mongodb_supabase" and "user:password@localhost" in self.postgres_dsn:
                raise ValueError("POSTGRES_DSN is still the development placeholder in production")
        return self

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
