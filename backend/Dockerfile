# DigiSanchaar — backend (FastAPI). Portable image: no cloud-provider assumptions.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/backend

# Production dependencies only (requirements-dev.txt is test tooling).
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY migrations ./migrations

# Run as an unprivileged user.
RUN useradd --system --uid 10001 --no-create-home quantix
USER quantix

EXPOSE 8000

# Liveness only (process is up). Use /api/v1/health/ready for orchestrator
# readiness: it checks MongoDB and PostgreSQL and returns 503 if either is down.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"

# --proxy-headers: client IPs (fraud/click logic) come from the reverse proxy.
# Set FORWARDED_ALLOW_IPS to your proxy's address(es) in production.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--workers", "2"]
