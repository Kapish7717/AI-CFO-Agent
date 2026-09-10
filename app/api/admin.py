"""Admin endpoints for user management and company settings.

Only admin users can access these endpoints. Admin is determined by the
'role' field in the users table (set to 'admin' for the first user of
each email domain during registration).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import get_admin_user_id
from app.db.database import (
    get_company_settings,
    get_users_by_domain,
    set_user_active,
    update_company_settings,
    update_user_role,
)

logger = logging.getLogger("cfo.api.admin")
router = APIRouter()


class UpdateUserRoleRequest(BaseModel):
    role: str  # 'admin' or 'user'


class UpdateUserStatusRequest(BaseModel):
    is_active: bool


class UpdateCompanyRequest(BaseModel):
    company_name: str | None = None


# --------------------------------------------------------------------------- #
# User management endpoints (admin only)
# --------------------------------------------------------------------------- #

@router.get("/api/admin/users")
def list_company_users(current_user: dict = Depends(get_admin_user_id)):
    """List all users in the same company (same email domain)."""
    from app.db.database import get_user_by_id
    user = get_user_by_id(current_user)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    domain = user.get("company_domain")
    if not domain:
        raise HTTPException(status_code=400, detail="No company domain associated with your account")

    users = get_users_by_domain(domain)
    return {
        "users": [
            {
                "id": u["id"],
                "email": u["email"],
                "full_name": u["full_name"],
                "role": u["role"],
                "is_active": u["is_active"],
                "created_at": u["created_at"].isoformat() if u.get("created_at") else None,
            }
            for u in users
        ],
        "company_domain": domain,
    }


@router.put("/api/admin/users/{user_id}/role")
def change_user_role(user_id: int, req: UpdateUserRoleRequest, admin_id: int = Depends(get_admin_user_id)):
    """Promote or demote a user (admin only)."""
    if req.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'")

    # Verify the target user is in the same company
    from app.db.database import get_user_by_id
    admin_user = get_user_by_id(admin_id)
    target_user = get_user_by_id(user_id)

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if admin_user.get("company_domain") != target_user.get("company_domain"):
        raise HTTPException(status_code=403, detail="Cannot modify users outside your company")

    if user_id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    success = update_user_role(user_id, req.role)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update user role")

    logger.info(f"Admin {admin_id} changed role of user {user_id} to {req.role}")
    return {"success": True, "user_id": user_id, "role": req.role}


@router.put("/api/admin/users/{user_id}/status")
def change_user_status(user_id: int, req: UpdateUserStatusRequest, admin_id: int = Depends(get_admin_user_id)):
    """Activate or deactivate a user (admin only)."""
    from app.db.database import get_user_by_id
    admin_user = get_user_by_id(admin_id)
    target_user = get_user_by_id(user_id)

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if admin_user.get("company_domain") != target_user.get("company_domain"):
        raise HTTPException(status_code=403, detail="Cannot modify users outside your company")

    if user_id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    success = set_user_active(user_id, req.is_active)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update user status")

    action = "activated" if req.is_active else "deactivated"
    logger.info(f"Admin {admin_id} {action} user {user_id}")
    return {"success": True, "user_id": user_id, "is_active": req.is_active}


# --------------------------------------------------------------------------- #
# Company settings endpoints (admin only)
# --------------------------------------------------------------------------- #

@router.get("/api/admin/company")
def get_company_info(admin_id: int = Depends(get_admin_user_id)):
    """Get company settings (admin only)."""
    from app.db.database import get_user_by_id
    admin_user = get_user_by_id(admin_id)
    if not admin_user:
        raise HTTPException(status_code=404, detail="User not found")

    domain = admin_user.get("company_domain")
    if not domain:
        raise HTTPException(status_code=400, detail="No company domain associated with your account")

    settings = get_company_settings(domain)
    users = get_users_by_domain(domain)

    return {
        "domain": domain,
        "company_name": settings.get("company_name") if settings else None,
        "user_count": len(users),
        "admin_count": sum(1 for u in users if u.get("role") == "admin"),
        "created_at": settings.get("created_at").isoformat() if settings and settings.get("created_at") else None,
    }


@router.put("/api/admin/company")
def update_company_info(req: UpdateCompanyRequest, admin_id: int = Depends(get_admin_user_id)):
    """Update company settings (admin only)."""
    from app.db.database import get_user_by_id
    admin_user = get_user_by_id(admin_id)
    if not admin_user:
        raise HTTPException(status_code=404, detail="User not found")

    domain = admin_user.get("company_domain")
    if not domain:
        raise HTTPException(status_code=400, detail="No company domain associated with your account")

    success = update_company_settings(domain, req.company_name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update company settings")

    logger.info(f"Admin {admin_id} updated company settings for {domain}")
    return {"success": True, "domain": domain, "company_name": req.company_name}
