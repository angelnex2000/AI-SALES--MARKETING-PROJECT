import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from app.models.user import Role

# bcrypt hashes at most 72 BYTES and silently ignores the rest, so without
# this two different passwords sharing a 72-byte prefix would both unlock the
# account. Rejecting is safer than truncating. Byte length, not character
# length — a non-ASCII password hits the limit sooner than it looks.
BCRYPT_MAX_BYTES = 72


def _within_bcrypt_limit(v: str) -> str:
    if len(v.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes when UTF-8 encoded")
    return v


Password = Annotated[str, Field(min_length=8), AfterValidator(_within_bcrypt_limit)]


class LoginRequest(BaseModel):
    email: EmailStr
    # Deliberately NOT the constrained Password type: login must accept
    # whatever is submitted and fail on credentials, not on validation.
    # A 422 here would tell an attacker their guess was malformed rather
    # than wrong, and would lock out users whose password predates a rule.
    password: str


class SignupRequest(BaseModel):
    """Creates a new company workspace and its first admin user."""

    company_name: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: Password


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Body, not query params: a reset token and a new password in a URL end
    up in proxy logs, browser history, and Referer headers."""

    token: str
    new_password: Password


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: Role
    company_id: uuid.UUID