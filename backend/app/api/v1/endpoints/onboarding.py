from fastapi import APIRouter, Depends

from app.core.rate_limit_dependency import rate_limit
from app.schemas.onboarding import ManagerSignupRequest, PublisherSignupRequest, SignupResponse
from app.services import onboarding_service

router = APIRouter()


@router.post(
    "/manager",
    response_model=SignupResponse,
    dependencies=[Depends(rate_limit("signup", limit=10, window_seconds=60))],
)
async def onboard_manager(body: ManagerSignupRequest):
    user = await onboarding_service.signup_manager(
        body.invite_token, body.email, body.password, body.display_name, mobile=body.mobile
    )
    return SignupResponse(user_id=str(user["_id"]), email=user["email"], account_status=user["account_status"])


@router.post(
    "/publisher",
    response_model=SignupResponse,
    dependencies=[Depends(rate_limit("signup", limit=10, window_seconds=60))],
)
async def onboard_publisher(body: PublisherSignupRequest):
    user = await onboarding_service.signup_publisher(
        body.invite_token, body.email, body.password, body.display_name,
        mobile=body.mobile, company=body.company,
    )
    return SignupResponse(user_id=str(user["_id"]), email=user["email"], account_status=user["account_status"])
