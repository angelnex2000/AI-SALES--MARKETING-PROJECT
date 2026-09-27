"""Module 2 — Authentication.

Tokens are delivered as httpOnly cookies (browser) so client-side JS can never
read them; `Bearer` remains available for API clients via get_current_user.
The login/signup response body returns only the user, never the raw token.
"""

import uuid

from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import DuplicateError, NotFoundError
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
from app.models.company import Company
from app.models.user import Role, User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    ResetPasswordRequest,
    SignupRequest,
)
from app.schemas.common import ok

router = APIRouter()

# Cookie lifetimes are derived from the token lifetimes, never hardcoded
# alongside them — a cookie that outlives its token logs the user out while
# the browser still believes the session is good.
_ACCESS_MAX_AGE = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
_REFRESH_MAX_AGE = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60

# Shared cookie attributes. delete_cookie must be given the same ones or some
# browsers keep the original cookie and logout silently fails.
#
# `secure` is off only in development. Browsers treat http://localhost as a
# secure context so it would work there regardless, but a dev box reached over
# plain http by IP or hostname would silently drop the cookie and every
# request would look unauthenticated. Staging and production always set it.
_COOKIE_KWARGS: dict[str, object] = {
    "httponly": True,
    "samesite": "lax",
    "secure": settings.ENVIRONMENT != "development",
}


def _set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    # httpOnly + Secure + SameSite: JS can't read it (XSS), but Next.js
    # middleware reads it server-side for role-based redirects. Real
    # authorization is still require_role(), not this cookie.
    response.set_cookie("access_token", access_token, max_age=_ACCESS_MAX_AGE, **_COOKIE_KWARGS)
    # Scoped to the one endpoint that consumes it, so the long-lived token is
    # not attached to every ordinary API call.
    response.set_cookie(
        "refresh_token",
        refresh_token,
        max_age=_REFRESH_MAX_AGE,
        path=f"{settings.API_V1_PREFIX}/auth/refresh-token",
        **_COOKIE_KWARGS,
    )


# Computed once at import so login can spend the same bcrypt time on an
# unknown email as on a real one. The value is irrelevant — only the cost is.
_DUMMY_PASSWORD_HASH = hash_password("not-a-real-password")


def _issue_session(response: Response, user_id, company_id, role: str) -> None:
    _set_auth_cookies(
        response,
        access_token=create_access_token(user_id=user_id, company_id=company_id, role=role),
        refresh_token=create_refresh_token(user_id=user_id, company_id=company_id, role=role),
    )


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise DuplicateError("Email already registered", error_code="EMAIL_TAKEN")

    company = Company(name=payload.company_name)
    db.add(company)
    await db.flush()  # get company.id before creating the user

    user = User(
        company_id=company.id,
        email=payload.email,
        full_name=payload.full_name,
        role=Role.ADMIN,  # first user of a new workspace is always admin
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        # The SELECT above is not a lock: two concurrent signups with the same
        # email both pass it, and the unique index rejects the loser. Without
        # this the user would see a 500 instead of the correct 409.
        await db.rollback()
        raise DuplicateError("Email already registered", error_code="EMAIL_TAKEN") from exc
    await db.refresh(user)
    return ok(
        data={"company_id": company.id, "user_id": user.id, "role": user.role.value},
        message="Signup successful",
    )


@router.post("/login")
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Always run a bcrypt verify, even for an unknown email. Short-circuiting
    # would return in microseconds for addresses that don't exist and ~100ms
    # for ones that do, which is enough to enumerate our customers' users.
    hashed = user.hashed_password if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(payload.password, hashed)

    # Generic message either way — never reveal whether the email exists.
    if user is None or not user.is_active or not password_ok:
        raise NotFoundError(
            "Invalid email or password", status_code=status.HTTP_401_UNAUTHORIZED, error_code="INVALID_CREDENTIALS"
        )

    _issue_session(response, user.id, user.company_id, user.role.value)
    return ok(
        data={
            "user": {
                "id": user.id,
                "full_name": user.full_name,
                "role": user.role.value,
                "company_id": user.company_id,
            }
        },
        message="Login successful",
    )


@router.post("/refresh-token")
async def refresh_token(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if refresh_token is None:
        raise NotFoundError(
            "No refresh token", status_code=status.HTTP_401_UNAUTHORIZED, error_code="NO_REFRESH_TOKEN"
        )
    try:
        # expected_type rejects an access token presented here — the two are
        # not interchangeable.
        payload = decode_token(refresh_token, expected_type=REFRESH_TOKEN_TYPE)
    except ValueError:
        # `from None` on purpose: the decode error can name the algorithm and
        # key state, and this response goes to an unauthenticated caller.
        raise NotFoundError(
            "Invalid refresh token", status_code=status.HTTP_401_UNAUTHORIZED, error_code="INVALID_REFRESH_TOKEN"
        ) from None

    # Re-read the user rather than trusting the token's claims: a role change,
    # deactivation, or deletion since the refresh token was issued must take
    # effect here, otherwise a 7-day token freezes yesterday's permissions.
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise NotFoundError(
            "Invalid refresh token", status_code=status.HTTP_401_UNAUTHORIZED, error_code="INVALID_REFRESH_TOKEN"
        )

    # TODO: check a Redis denylist so a logged-out refresh token can't be reused.
    _issue_session(response, user.id, user.company_id, user.role.value)
    return ok(message="Token refreshed")


@router.post("/logout")
async def logout(response: Response):
    # TODO: add the refresh token's jti to a Redis denylist for real revocation.
    # Until then a stolen token stays valid until it expires; clearing the
    # cookies only ends the session in this browser.
    # Attributes must match the ones used at set time (including the refresh
    # cookie's narrower path) or the browser keeps the original cookie.
    response.delete_cookie("access_token", **_COOKIE_KWARGS)
    response.delete_cookie(
        "refresh_token", path=f"{settings.API_V1_PREFIX}/auth/refresh-token", **_COOKIE_KWARGS
    )
    return ok(message="Logged out")


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return ok(data=MeResponse.model_validate(current_user))


# --- Email-driven flows (verification + password reset). Endpoints exist and
# validate input; the actual email dispatch is wired with the email integration.


@router.post("/verify-email")
async def verify_email(token: str):
    return ok(message="Email verification not yet wired (token accepted)")


@router.post("/resend-verification")
async def resend_verification(email: str):
    return ok(message="Verification email queued (pending email integration)")


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest):
    # Always 200 — never reveal whether the email exists.
    return ok(message="If that account exists, a reset link has been sent")


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest):
    # Body, not query params: a reset token and a plaintext new password in a
    # URL are recorded by proxies, CDNs, server access logs, and browser
    # history, and leak via the Referer header.
    return ok(message="Password reset not yet wired (token accepted)")
