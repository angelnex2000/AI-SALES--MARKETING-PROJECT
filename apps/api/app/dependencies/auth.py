import uuid

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.dependencies.db import get_db
from app.models.user import Role, User


def _extract_token(access_token: str | None, authorization: str | None) -> str | None:
    """Cookie first, then `Authorization: Bearer`.

    Browsers use the httpOnly cookie so JS can never read the token. Non-browser
    API clients have no cookie jar, so the Bearer header is the supported path
    for them. Cookie wins when both are present: it is the one the browser
    attaches automatically and cannot be set by a cross-site attacker.
    """

    if access_token:
        return access_token
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            return credentials.strip()
    return None


async def get_current_user(
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolves the caller from the httpOnly JWT cookie (browser) or a Bearer
    header (API clients). This — not the frontend's middleware redirect — is
    the actual security boundary. Frontend hiding is convenience; this is
    authorization."""

    token = _extract_token(access_token, authorization)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    try:
        # expected_type stops a long-lived refresh token being used as an
        # access token on ordinary endpoints.
        payload = decode_token(token, expected_type=ACCESS_TOKEN_TYPE)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        # A token we signed but with a malformed `sub` — treat as unauthenticated
        # rather than letting uuid.UUID raise a 500 out of a dependency.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_role(*allowed_roles: Role):
    """Central RBAC gate. Every protected router depends on this — never on
    the frontend having hidden a page."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this role")
        return user

    return _check