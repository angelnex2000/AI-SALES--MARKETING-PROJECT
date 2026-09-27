from datetime import UTC, datetime, timedelta
from uuid import UUID

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def _create_token(*, user_id: UUID, company_id: UUID, role: str, token_type: str, expires: timedelta) -> str:
    payload = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": role,
        # The `type` claim is what keeps the two tokens from being
        # interchangeable. Without it a stolen refresh token works as an
        # access token, and a short-lived access token is accepted at the
        # refresh endpoint.
        "type": token_type,
        "exp": datetime.now(UTC) + expires,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(*, user_id: UUID, company_id: UUID, role: str) -> str:
    """Short-lived, sent on every request. Claims carry company_id and role
    because both the frontend middleware (UX redirect only) and the backend
    require_role() dependency (the real boundary) need them without an extra
    DB round trip."""

    return _create_token(
        user_id=user_id,
        company_id=company_id,
        role=role,
        token_type=ACCESS_TOKEN_TYPE,
        expires=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(*, user_id: UUID, company_id: UUID, role: str) -> str:
    """Long-lived, used only at /auth/refresh-token to mint a new access
    token. Its lifetime must match the refresh cookie's max_age, or the
    session dies while the browser still holds a cookie it believes is good."""

    return _create_token(
        user_id=user_id,
        company_id=company_id,
        role=role,
        token_type=REFRESH_TOKEN_TYPE,
        expires=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, *, expected_type: str) -> dict:
    """Decodes and verifies the token is of the expected kind. Callers must
    say which they want — never accept whichever token happens to arrive."""

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
    if payload.get("type") != expected_type:
        raise ValueError(f"Expected a {expected_type} token")
    return payload


def _fernet() -> Fernet:
    if not settings.ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY is not set — required to store CRM credentials at rest")
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt_secret(plaintext: str) -> str:
    """Used for integration OAuth tokens (Integration.access_token_encrypted /
    refresh_token_encrypted) — never store a customer's
    Salesforce/HubSpot/Zoho/Gmail/Slack token in plaintext."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()