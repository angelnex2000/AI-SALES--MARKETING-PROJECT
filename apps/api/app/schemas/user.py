import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.models.user import Role


class UserStatus(str, Enum):
    INVITED = "invited"
    ACTIVE = "active"
    INACTIVE = "inactive"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool
    company_id: uuid.UUID
    created_at: datetime


class UserCreate(BaseModel):
    """Admin-invites-user. No password field — the invited user sets their own
    via the verify-email / reset-password flow. `role` is the string enum, not
    a role_id (there is no roles table)."""

    full_name: str
    email: EmailStr
    role: Role

    @field_validator("role")
    @classmethod
    def role_must_be_assignable(cls, v: Role) -> Role:
        # `customer` is external (no login) and never assignable to a platform
        # user. The other four are fine.
        if v not in (Role.ADMIN, Role.SALES_MANAGER, Role.SALES_EXECUTIVE, Role.MARKETING):
            raise ValueError("role is not assignable to a platform user")
        return v


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
