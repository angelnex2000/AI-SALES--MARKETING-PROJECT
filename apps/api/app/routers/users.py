"""Module 3 — Users, Roles, Permissions.

Mounted at `/api/v1` because it owns `/users/*`, `/roles`, and `/permissions`.
There are NO roles/permissions tables — `/roles` and `/permissions` return
hard-coded constants for the frontend to render dropdowns and hints; the real
authorization boundary is `require_role()`.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateError, ForbiddenError, NotFoundError
from app.dependencies.auth import require_role
from app.dependencies.db import get_db
from app.models.user import Role, User
from app.schemas.common import ok
from app.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter()

# The page × role matrix from CLAUDE.md — served as a constant so the frontend
# renders permission hints without a DB lookup.
_PERMISSION_MATRIX = {
    "dashboard": {"admin": "full", "sales_manager": "full", "sales_executive": "limited", "marketing": "full"},
    "leads": {"admin": "read", "sales_manager": "full", "sales_executive": "assigned", "marketing": "read"},
    "deals": {"admin": "read", "sales_manager": "full", "sales_executive": "assigned", "marketing": "read"},
    "campaigns": {"admin": "read", "sales_manager": "approve", "sales_executive": "view", "marketing": "full"},
    "outreach": {"admin": "none", "sales_manager": "review", "sales_executive": "full", "marketing": "draft"},
    "meetings": {"admin": "read", "sales_manager": "view", "sales_executive": "full", "marketing": "none"},
    "analytics": {"admin": "full", "sales_manager": "full", "sales_executive": "limited", "marketing": "full"},
    "ai_center": {"admin": "full", "sales_manager": "view", "sales_executive": "none", "marketing": "none"},
    "team": {"admin": "full", "sales_manager": "view", "sales_executive": "none", "marketing": "none"},
    "integrations": {"admin": "full", "sales_manager": "none", "sales_executive": "none", "marketing": "none"},
    "billing": {"admin": "full", "sales_manager": "none", "sales_executive": "none", "marketing": "none"},
}


@router.get("/roles")
async def list_roles(_: User = Depends(require_role(Role.ADMIN, Role.SALES_MANAGER))):
    return ok(data=[r.value for r in Role])


@router.get("/permissions")
async def list_permissions(_: User = Depends(require_role(Role.ADMIN))):
    return ok(data=_PERMISSION_MATRIX)


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN, Role.SALES_MANAGER)),
):
    rows = await db.execute(select(User).where(User.company_id == user.company_id))
    return ok(data=[UserResponse.model_validate(u) for u in rows.scalars().all()])


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN)),
):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise DuplicateError("A user with this email already exists", error_code="EMAIL_TAKEN")

    # Invited: no password yet, inactive until they set one via the
    # verify-email / reset-password flow. Empty hash can never verify.
    new_user = User(
        company_id=user.company_id,
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role,
        hashed_password="",
        is_active=False,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    # NOTE: enqueue invite email here once the email integration is wired.
    return ok(data=UserResponse.model_validate(new_user), message="User invited")


@router.get("/users/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN, Role.SALES_MANAGER)),
):
    target = await db.get(User, user_id)
    if target is None or target.company_id != user.company_id:
        raise NotFoundError("User not found", error_code="USER_NOT_FOUND")
    return ok(data=UserResponse.model_validate(target))


@router.put("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN)),
):
    target = await _load_same_company_user(db, user_id, user)
    data = payload.model_dump(exclude_none=True)
    # Demoting/deactivating the last admin would lock the tenant out.
    if _would_remove_last_admin(target, data):
        await _guard_last_admin(db, user.company_id)
    for field, value in data.items():
        setattr(target, field, value)
    await db.commit()
    await db.refresh(target)
    return ok(data=UserResponse.model_validate(target), message="User updated")


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN)),
):
    """Soft delete — deactivate rather than remove (preserves audit trail)."""

    target = await _load_same_company_user(db, user_id, user)
    if target.role == Role.ADMIN:
        await _guard_last_admin(db, user.company_id)
    target.is_active = False
    await db.commit()
    return ok(message="User deactivated")


async def _load_same_company_user(db: AsyncSession, user_id: uuid.UUID, actor: User) -> User:
    target = await db.get(User, user_id)
    if target is None or target.company_id != actor.company_id:
        raise NotFoundError("User not found", error_code="USER_NOT_FOUND")
    return target


def _would_remove_last_admin(target: User, data: dict) -> bool:
    if target.role != Role.ADMIN:
        return False
    demoting = "role" in data and data["role"] != Role.ADMIN
    deactivating = data.get("is_active") is False
    return demoting or deactivating


async def _guard_last_admin(db: AsyncSession, company_id: uuid.UUID) -> None:
    count = await db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.company_id == company_id, User.role == Role.ADMIN, User.is_active.is_(True))
    )
    if (count or 0) <= 1:
        raise ForbiddenError("Cannot remove the last active admin", error_code="LAST_ADMIN")
