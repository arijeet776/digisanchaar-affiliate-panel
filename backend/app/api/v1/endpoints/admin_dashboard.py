from fastapi import APIRouter, Depends

from app.core.enums import Role
from app.core.rbac import CurrentUser, require_role
from app.services import dashboard_service

router = APIRouter()

_super_admin_only = require_role(Role.SUPER_ADMIN)


@router.get("")
async def get_dashboard(user: CurrentUser = Depends(_super_admin_only)):
    return await dashboard_service.get_dashboard()
