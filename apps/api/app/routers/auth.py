from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_password
from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, MeResponse

router = APIRouter()


@router.post("/login")
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    token = create_access_token(user_id=user.id, company_id=user.company_id, role=user.role.value)

    # httpOnly so client-side JS can never read the raw token (XSS
    # mitigation) — but Next.js middleware.ts runs server-side/edge and CAN
    # still read httpOnly cookies for its redirect-only role check. Real
    # authorization still happens via require_role(), not this cookie read.
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=60 * 60,
    )
    return {"id": user.id, "email": user.email, "role": user.role}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"status": "logged_out"}


@router.get("/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user