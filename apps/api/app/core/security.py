from datetime import datetime, timedelta, timezone
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


def create_access_token(*, user_id: UUID, company_id: UUID, role: str) -> str:
    """Claims carry company_id and role because both the frontend middleware
    (UX redirect only) and the backend require_role() dependency (the real
    boundary) need them without an extra DB round trip."""

    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "company_id": str(company_id), "role": role, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc


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