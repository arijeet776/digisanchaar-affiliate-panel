"""
Public click endpoint (Part 5) — no authentication BY DESIGN: this is the
public tracking link target. Security is the pipeline order inside
tracking_service.process_click (spec §24), not a session.

Mounted twice:
- /api/v1/t/{campaign_code}/{link_code}   (this router — preview/testing)
- /{campaign_code}/{link_code}            (app root via main.py — production,
  where the tracking domain points directly at the backend)
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from app.core.rate_limit_dependency import rate_limit
from app.services import tracking_service

router = APIRouter()

click_route_dependencies = [Depends(rate_limit("tracking_click", limit=60, window_seconds=60))]


def _candidate_ips(request: Request) -> list[str]:
    """Every IP candidate is checked against the block registry — trusting
    only X-Forwarded-For would let a client spoof its way around a block."""
    candidates = []
    # request.client.host FIRST: with uvicorn --proxy-headers it is the address the trusted proxy appended, so a
    # client cannot choose it. The raw left-most X-Forwarded-For entry is client-controlled: it is still checked
    # against the block list, but it is never the IP that gets stored / used for velocity.
    if request.client:
        candidates.append(request.client.host)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first and first not in candidates:
            candidates.append(first)
    return candidates


@router.get("/{campaign_code}/{link_code}", dependencies=click_route_dependencies)
async def handle_click(campaign_code: str, link_code: str, request: Request):
    result = await tracking_service.process_click(
        campaign_code,
        link_code,
        request.query_params,
        _candidate_ips(request),
        request.headers.get("user-agent", ""),
    )
    if result["action"] == "redirect":
        return RedirectResponse(url=result["url"], status_code=302)
    return PlainTextResponse(result["message"], status_code=result["status"])
