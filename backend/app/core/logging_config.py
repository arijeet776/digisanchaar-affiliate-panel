"""
Structured logging.

Postback/webhook debugging in later parts needs traceability without leaking
secrets (postback URLs, tokens) into logs — callers are responsible for
redacting sensitive fields before logging them; this module just standardizes
format and adds request_id when available.
"""
import logging
import sys
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def configure_logging(environment: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    fmt = "%(asctime)s | %(levelname)s | req=%(request_id)s | %(name)s | %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if environment == "development" else logging.INFO)

    # Quiet noisy third-party loggers by default
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
